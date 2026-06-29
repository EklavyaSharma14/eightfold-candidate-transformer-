# Eightfold Multi-Source Candidate Data Transformer

Turns messy candidate data from multiple systems into one clean, canonical
profile per candidate — normalized formats, deduplicated values, and a
full record of where every value came from and how confident we are in it.

Built for the Eightfold Engineering Intern (Jul–Dec 2026) assignment. The
design rationale lives in `design/` (the one-pager); this README is about
running the thing.

## Quick start

```bash
pip install -r requirements.txt --break-system-packages   # or use a venv

# Default output schema, all 3 sample candidates:
python cli.py run --manifest data/manifest.json --pretty

# A custom runtime config (renamed/subset fields, national phone format,
# provenance off, missing-required-field errors loudly):
python cli.py run --manifest data/manifest.json --config configs/recruiter_lite.json --pretty

# Write to a file instead of stdout:
python cli.py run --manifest data/manifest.json --out outputs/default_output.json --pretty

# Run the tests:
python -m pytest tests/ -v
```

No API keys or network access needed — the GitHub source uses a cached
fixture by default (see "Sources used" below).

## What's in `data/`

Three fabricated candidates, deliberately built to exercise the merge
logic rather than to look tidy:

| Candidate | What it's testing |
|---|---|
| **C-1001** Asha Verma | Sources mostly agree → high confidence, clean multi-source merge, agreement boosts. |
| **C-1002** Daniel Cho | A real conflict (ATS says "Senior Software Engineer", CSV *and* notes both say "Software Engineer II") — proves a single high-priority source beats two low-priority sources that agree with each other. Also: a phone with no country code, and skills written as casual abbreviations ("JS", "Py") in free text. |
| **C-1003** Priya Nair | The "garbage source" candidate: a malformed ATS JSON file, a GitHub fixture path that doesn't exist, and an empty notes file. Only the CSV survives. Confirms the pipeline doesn't crash and that `overall_confidence` honestly reflects how little corroboration the profile has. |

`data/manifest.json` is the orchestration layer's crosswalk: for each
`candidate_id`, which row/record/file in each system belongs to them (see
**Assumptions** below for why this is a deliberate scope boundary, not an
oversight).

## Sources used

Two structured, two unstructured (the brief asks for at least one of
each):

- **CSV** (`data/recruiter_export.csv`) — recruiter export, our own column names.
- **ATS JSON** (`data/ats_export.json`) — its *own* field names on purpose
  (`applicant_name`, `mobile_number`, `city_country`, `work_history`, ...),
  remapped in `extractors.py`.
- **GitHub profile** (`data/github_fixture_*.json`) — a cached JSON
  fixture shaped like the real GitHub API (`/users/{u}` + `/users/{u}/repos`
  merged). `extractors.py` also has a `mode="live"` path that hits the real
  API with `urllib` and fails soft (returns nothing usable rather than
  raising) — it's just not exercised by the tests, so CI/grading stays
  deterministic and offline.
- **Recruiter notes** (`data/notes_*.txt`) — free text, parsed with
  regex/keyword heuristics for email, phone, years of experience, a couple
  of labeled lines (`Title:`, `Location:`), and skill mentions (matched
  against the same alias dictionary the normalizer canonicalizes against).

## Pipeline

```
detect → extract → normalize → merge → confidence → project → validate
```

- `extractors.py` — one function per source type, pulls a raw,
  not-yet-normalized record out of each source. Never raises for "the data
  was weird"; only raises for "the source itself is unusable" (missing
  file, bad JSON, no matching record) — and even that is caught one level
  up and turned into a logged, skipped source.
- `normalizers.py` — phone → E.164 (`phonenumbers`), date → `YYYY-MM`
  (best-effort, flags year-only dates as low precision, treats
  "Present"/"Current" as open-ended rather than inventing an end date),
  country → ISO 3166-1 alpha-2 (`pycountry` + a small alias table, with a
  deliberate guard against reading a US state code like `CA` as the
  country Canada), skill → canonical name via an alias table. Names are
  trimmed/whitespace-collapsed but **never re-cased** — auto-titlecasing
  breaks real names ("O'Brien"), which is exactly the kind of
  confident-but-wrong move the brief warns against.
- `merge.py` — per-field source-priority weights (see `source_priority.py`)
  decide who wins a conflict; agreeing sources boost confidence, disagreeing
  ones cost some. List fields (emails, phones, skills, experience,
  education) are unioned and deduplicated, not winner-take-all. Every
  contributing and overridden value is kept in `provenance`.
- `project.py` — the runtime-config / projection layer. The **default
  output schema runs through the exact same code path** as any custom
  config (`DEFAULT_CONFIG` in `project.py`); there's no separate
  "default mode" branch to keep in sync.
- `validate.py` — a second, independent pass after projection that checks
  the actual output matches what the config asked for, before the
  pipeline hands it back.

## Runtime config (the "required twist")

```bash
python cli.py run --manifest data/manifest.json --config configs/recruiter_lite.json --pretty
```

`configs/recruiter_lite.json` demonstrates every knob from the brief in one
file: subsetting fields, renaming (`id` ← `candidate_id`), pulling from an
array index (`emails[0]`), overriding normalization (`phones[0]` displayed
as a national-format string instead of E.164), turning provenance off
while keeping confidence on, and `on_missing: "error"` — which, on the
sample data, fires for exactly **one** candidate (C-1003 has no surviving
source for `years_experience`) while C-1001 and C-1002 succeed normally.
That one failure shows up as an error record for that candidate; it does
not take down the rest of the batch.

Config shape:
```jsonc
{
  "fields": [
    { "path": "<output key>", "from": "<canonical.path[0]>", "type": "string|number|boolean|string[]|object|object[]", "required": true, "normalize": "national" }
  ],
  "include_confidence": true,   // also strips per-skill confidence when false
  "include_provenance": true,   // also controls source_errors (see below)
  "on_missing": "null|omit|error"
}
```

`from` supports `field`, `field.subfield`, `field[0]`, and `field[].subfield`
(maps over every item in a list, e.g. `skills[].name`).

## Output schema (default)

Matches the brief's table, plus one addition: `source_errors` (which
sources we tried and skipped, and why), surfaced alongside `provenance`
since both answer "why does this profile look the way it does." It's
controlled by the same `include_provenance` toggle.

## Assumptions

- **Cross-source identity is given, not inferred.** The manifest tells us
  which CSV row / ATS record / GitHub fixture / notes file belongs to a
  given `candidate_id`. Matching "Bob Smith" the resume to `bsmith92` on
  GitHub with no shared identifier is a real, separate ML/heuristics
  problem — see **Descoped** below.
- A recruiter CSV export realistically includes a `location` and
  `start_date` column even though the brief's example only lists
  name/email/phone/current_company/title; kept since it's "yours to
  refine" and it's what a real export looks like.
- Location strings are parsed as `City[, Region][, Country]` by naive
  comma-splitting. Good enough for the sample data; a 2-letter token in
  the country slot is checked against US state codes first (so "San
  Francisco, CA" doesn't resolve to Canada) before trying country lookup.

## Edge cases handled (see tests for each)

1. **Missing/corrupt source** — malformed JSON, a fixture path that
   doesn't exist, an empty notes file. Each is logged in `source_errors`
   and skipped; the candidate still gets a profile from what's left.
2. **Conflicting values** — highest-priority source wins, confidence
   takes a penalty, losers stay in `provenance`. Two weak sources agreeing
   with each other doesn't outvote one strong source (see C-1002's title).
3. **Partial/messy dates** — year-only ("2019") parses to `2019-01` with a
   precision note rather than a confident-looking fake month; "Present"
   is treated as open-ended, not coerced into a real date.
4. **Phone with no country code and no location hint** — falls back to a
   configured default region, but the result is explicitly flagged as a
   guess (lower confidence) rather than presented as a clean parse.
5. **Same skill, different spelling/case** ("ReactJS"/"React.js"/"js"/"py")
   — canonicalized via an alias table and merged into one entry with a
   combined source list.

## Descoped (would do with more time)

- **Fuzzy cross-source identity resolution** when there's no shared ID —
  deliberately pushed to the manifest/orchestration layer; doing it well
  (name + company + email similarity, confidence-scored) is its own
  project.
- **Resume PDF/DOCX parsing** — used GitHub + notes as the two
  unstructured sources instead, since layout-aware resume extraction
  varies wildly by template and deserves dedicated effort. The extractor
  interface (`extract_source(spec, base_dir) -> (raw_record, type, error)`)
  is pluggable, so a resume extractor is one more module, not a redesign.
- **Live GitHub calls in tests/CI** — the live-fetch code path exists
  (`extractors._fetch_github_live`) but isn't exercised by the test suite,
  to keep results deterministic and runnable offline.
- **NER-based skill extraction from free text** — dictionary + keyword
  matching only; won't generalize to truly open-vocabulary skill mentions.
- **Location agreement bonus** only fires on an *exact* (city, region,
  country) match across sources; a source missing just the `region`
  doesn't get credited as "agreeing" with one that has it, even though
  they're both right about city+country. The priority-weighted winner is
  still correct either way — this only affects the cosmetic confidence
  boost, not correctness.
- A real UI — CLI only, per the brief's explicit lower priority on this.

## Repo layout

```
cli.py                      thin CLI entry point
src/transformer/
  extractors.py              detect + extract (per source type)
  normalizers.py              normalize (phone/date/country/skill/name)
  source_priority.py          per-field source reliability weights
  merge.py                    merge + confidence + provenance
  project.py                  runtime-config projection layer
  validate.py                 config sanity check + output shape check
  pipeline.py                  orchestrates the above per-candidate, per-batch
data/                         fabricated sample sources + manifest.json
configs/recruiter_lite.json   example custom output config
outputs/                      produced output (committed, see below)
tests/                        pytest suite (35 tests)
design/                       the one-page design doc (PDF)
```

`outputs/default_output.json` and `outputs/recruiter_lite_output.json` are
the actual output produced by running the two commands above against
`data/manifest.json` — committed as requested, not regenerated at review
time, though it's deterministic so re-running reproduces them exactly.
