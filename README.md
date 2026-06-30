# Multi-Source Candidate Data Transformer

This is my submission for the Eightfold engineering intern assignment (Jul-Dec 2026). The short version: it pulls candidate info from four different, messy sources and produces one clean profile per candidate, with a confidence score and a record of exactly where every value came from.

The full reasoning behind the design choices is in `design/` as a one-pager. This file is more about how to actually run things and what's where.

## Running it

```bash
pip install -r requirements.txt --break-system-packages   # or just use a venv if you'd rather

# default schema, all 3 sample candidates
python cli.py run --manifest data/manifest.json --pretty

# a custom config - subset/rename fields, national phone format, on_missing=error
python cli.py run --manifest data/manifest.json --config configs/recruiter_lite.json --pretty

# write to a file instead of printing
python cli.py run --manifest data/manifest.json --out outputs/default_output.json --pretty

# tests
python -m pytest tests/ -v
```

Doesn't need network access or any API keys - GitHub is read from a cached fixture by default, more on that below.

## The sample candidates

I made up three candidates instead of using real data, mostly so I could engineer specific situations into the test data rather than hoping real data happened to have interesting edge cases.

**C-1001, Asha Verma** — everything basically agrees across all four sources. This is the baseline / happy path, ends up with overall_confidence around 0.92.

**C-1002, Daniel Cho** — has a real conflict. His CSV and his recruiter notes both say "Software Engineer II", but the ATS record says "Senior Software Engineer". I used this one to prove that priority weighting actually works - one trustworthy source should beat two weaker ones that happen to agree with each other, not the other way around. Also threw in a phone number with no country code and some skills written in shorthand ("js", "py") to test normalization.

**C-1003, Priya Nair** — basically everything that could go wrong, does. The ATS JSON file has a syntax error in it (missing closing brace situation, deliberately), the GitHub fixture path points at a file that doesn't exist, and the notes file is just empty. Only the CSV survives. This tests that the pipeline degrades gracefully instead of just crashing, and that the confidence score honestly reflects how thin the resulting profile is (it comes out around 0.53, noticeably lower than Asha's).

`data/manifest.json` ties candidate IDs to which file/record in each source belongs to them - see the Assumptions section for why I didn't try to solve that matching problem automatically.

## The four sources

Two structured, two unstructured, per the brief:

- **CSV** (`data/recruiter_export.csv`) — a recruiter export, fairly clean column names.
- **ATS JSON** (`data/ats_export.json`) — uses its own field names on purpose (`applicant_name`, `mobile_number`, `city_country`, `work_history`...) since that's realistic for a real ATS export, and `extractors.py` maps those onto our own field names.
- **GitHub profile** (`data/github_fixture_*.json`) — a cached fixture shaped like the actual GitHub API response. There's also a `mode="live"` path in extractors.py that hits the real API, but it's not used by tests so things stay deterministic and runnable offline.
- **Recruiter notes** (`data/notes_*.txt`) — plain text, parsed with some regex and keyword matching for email/phone/years of experience, plus a couple labeled lines like `Title:` and `Location:`, and skill mentions matched against the same alias table the normalizer uses.

## How it's structured

```
detect -> extract -> normalize -> merge -> confidence -> project -> validate
```

`extractors.py` has one function per source type that pulls raw data out. These never throw an error just because the data inside looks weird - they only raise when the source itself can't be read at all (file missing, bad JSON, no matching record), and even then it's caught one level up and logged instead of crashing anything.

`normalizers.py` handles phone numbers (-> E.164 via the `phonenumbers` library), dates (-> YYYY-MM, with year-only dates flagged as lower precision instead of guessing a month, and "Present"/"Current" treated as open-ended rather than a fake end date), countries (-> ISO alpha-2 codes, with a manual check for US state abbreviations so "CA" doesn't get read as Canada), and skills (-> a canonical name via an alias dictionary). Names just get trimmed and whitespace-collapsed, not re-cased, since auto-titlecasing breaks names like O'Brien.

`merge.py` is where conflicts actually get resolved. Each field has a priority table (in `source_priority.py`) saying which source to trust more for that particular field. Agreeing sources bump confidence up a bit, disagreeing ones bring it down. List-type fields (emails, skills, etc.) get unioned instead of picking a winner, since a person can genuinely have two emails but not two different "current" job titles.

`project.py` is the config layer. The default output schema is literally just the config the brief describes, written down as a Python dict, and it goes through the exact same `project()` function as any custom config would. That's what makes it possible to reshape the output without touching this file.

`validate.py` runs after projection, as a second pass checking the output actually matches what was asked for before the pipeline returns anything.

## The runtime config part

```bash
python cli.py run --manifest data/manifest.json --config configs/recruiter_lite.json --pretty
```

`configs/recruiter_lite.json` is the example I built to cover all the things the brief mentions - subsetting fields, renaming them (`id` instead of `candidate_id`), pulling a specific array index (`emails[0]`), overriding how a value gets displayed (`phones[0]` shown in national format instead of raw E.164), turning provenance off while leaving confidence on, and `on_missing: "error"`.

That last one is worth a closer look - on the sample data it fires for exactly one candidate. C-1003 doesn't have a surviving source for `years_experience` (her ATS record, which would've had it, is the one that's corrupted), so that candidate comes back as an error record while C-1001 and C-1002 process fine. One bad candidate doesn't take the rest of the batch down.

Config shape, roughly:
```jsonc
{
  "fields": [
    { "path": "<output key>", "from": "<canonical.path[0]>", "type": "string|number|boolean|string[]|object|object[]", "required": true, "normalize": "national" }
  ],
  "include_confidence": true,
  "include_provenance": true,
  "on_missing": "null|omit|error"
}
```

`from` paths support `field`, `field.subfield`, `field[0]`, and `field[].subfield` (the last one maps over a whole list, e.g. `skills[].name` to get just the names).

## Output schema

Matches what's in the brief, plus one thing I added: `source_errors`, which lists which sources failed and why for a given candidate. It sits next to `provenance` since both are basically answering "why does this profile look the way it does", and it's controlled by the same `include_provenance` toggle.

## Assumptions I made

- I'm assuming the manifest already knows which record in each system belongs to which candidate. Actually figuring that out automatically - matching "Bob Smith" the resume to `bsmith92` on GitHub with no shared ID between them - is its own hard problem (entity resolution), and I didn't think I could do it justice in the time I had, so I scoped it out (more below).
- I added `location` and `start_date` columns to the CSV even though the brief's example table didn't list them, since that's what a real recruiter export would actually have, and the brief said the schema was mine to refine.
- Location parsing is just splitting on commas (`City, Region, Country`), which is good enough for the sample data but obviously not bulletproof. I did add a check for US state abbreviations specifically because I ran into the bug myself - "San Francisco, CA" was getting parsed as Canada before I caught it, since CA is both a US state and an ISO country code.

## Edge cases I tested for

1. Missing or corrupt sources (bad JSON, a fixture file that doesn't exist, an empty notes file) - logged, skipped, the candidate still gets whatever's left.
2. Conflicting values across sources - higher-priority source wins, confidence takes a small hit, the loser stays recorded in provenance instead of getting thrown away.
3. Messy dates - year-only gets flagged as low precision rather than a confident fake month, "Present" doesn't get coerced into a real date.
4. Phone numbers with no country code and no location to infer one from - falls back to a default region but flags the result as a guess (lower confidence), doesn't pretend it's a clean parse.
5. Same skill written differently across sources ("ReactJS" / "React.js" / "js") - all canonicalize to one entry with the combined list of sources.

## What I left out (and why)

Honestly the biggest thing is entity resolution - matching records across sources when there's no shared ID. I think doing it properly (name + company + email similarity, with its own confidence scoring) is a real project on its own, so I pushed it up to the manifest/orchestration layer instead of trying to half-solve it here.

I also skipped resume parsing and used GitHub + notes as my two unstructured sources instead. Resume layouts vary so much that extracting structured info reliably from PDFs/DOCX felt like it deserved its own focused effort rather than something I could bolt on. The extractor interface is the same shape for every source type though, so adding a resume extractor later is mostly just writing one more function, not redesigning anything.

The live GitHub API path exists in the code but isn't used by any test, just to keep CI deterministic and offline-runnable.

Skill detection in free text is just dictionary + keyword matching - it won't catch a skill it's never seen before, no real NLP going on there.

One small thing: the confidence boost for "sources agree on location" only fires if city, region, AND country all match exactly. If one source is missing just the region, it doesn't get counted as agreeing even though it's not really wrong. Doesn't affect which value wins, just slightly understates the confidence bump in that specific case.

And no real UI, just a CLI - the brief said this was explicitly lower priority, so I didn't spend time on it.

## Where everything is

```
cli.py                      entry point you actually run
src/transformer/
  extractors.py              pulls raw data out of each source
  normalizers.py             phone/date/country/skill/name cleanup
  source_priority.py         which source to trust more, per field
  merge.py                   conflict resolution + confidence + provenance
  project.py                 the config/output-shaping layer
  validate.py                checks the final output matches the config
  pipeline.py                ties all of the above together per candidate
data/                        the made-up sample sources + manifest.json
configs/recruiter_lite.json  example custom output config
outputs/                     output from actually running this, committed
tests/                       35 pytest tests
design/                      the one-page design doc PDF
```

`outputs/default_output.json` and `outputs/recruiter_lite_output.json` are real output from running the two commands above - I committed them rather than regenerating at review time, though since everything's deterministic, re-running gives you the exact same thing.
