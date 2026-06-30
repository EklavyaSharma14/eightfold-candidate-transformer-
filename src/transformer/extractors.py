"""
One function per source type. Each takes a `spec` (an entry from the
manifest) and base_dir, returns (raw_record, source_type, error_or_None).

raw_record is loosely-canonical -- whatever this source could plausibly
contribute, still in raw/unnormalized form:

    {
        "full_name": str|None,
        "emails": [str, ...],
        "phones": [str, ...],
        "location_raw": str|None,                 # "City, Country" free text
        "headline": str|None,
        "years_experience_raw": number|str|None,
        "skills_raw": [str, ...],
        "experience_raw": [{"company","title","start","end","summary"}, ...],
        "education_raw": [{"institution","degree","field","end_year"}, ...],
        "links_raw": {"linkedin": str|None, "github": str|None,
                       "portfolio": str|None, "other": [str, ...]},
    }

Extractors don't raise for "the data inside the file looked weird" -- they
just leave fields blank. They DO raise for "the source itself can't be
read" (missing file, bad JSON, no matching record) -- extract_source()
below catches that and turns it into a logged, skipped source instead of
crashing the whole run.
"""
import csv
import json
import os
import re
import urllib.request
import urllib.error


def _path(base_dir, path):
    return path if os.path.isabs(path) else os.path.join(base_dir, path)


def empty_record():
    return {
        "full_name": None,
        "emails": [],
        "phones": [],
        "location_raw": None,
        "headline": None,
        "years_experience_raw": None,
        "skills_raw": [],
        "experience_raw": [],
        "education_raw": [],
        "links_raw": {"linkedin": None, "github": None, "portfolio": None, "other": []},
    }


# ---- recruiter CSV export (structured #1) ----
def extract_csv(spec, base_dir):
    path = _path(base_dir, spec["path"])
    match = spec["match"]
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if r.get(match["column"]) == match["value"]]
    if not rows:
        raise ValueError(f"no CSV row in {spec['path']} where {match['column']}={match['value']!r}")
    row = rows[0]

    rec = empty_record()
    rec["full_name"] = row.get("name") or None
    if row.get("email"):
        rec["emails"] = [row["email"]]
    if row.get("phone"):
        rec["phones"] = [row["phone"]]
    rec["headline"] = row.get("title") or None
    rec["location_raw"] = row.get("location") or None
    if row.get("current_company") or row.get("title"):
        rec["experience_raw"] = [{
            "company": row.get("current_company") or None,
            "title": row.get("title") or None,
            "start": row.get("start_date") or None,
            "end": None,  # current role: open-ended
            "summary": None,
        }]
    if row.get("linkedin_url"):
        rec["links_raw"]["linkedin"] = row["linkedin_url"]
    return rec


# ---- ATS JSON blob -- own field names on purpose, gets remapped below ----
def extract_ats_json(spec, base_dir):
    path = _path(base_dir, spec["path"])
    match = spec["match"]
    with open(path, encoding="utf-8") as f:
        records = json.load(f)  # bad JSON -> JSONDecodeError, caught by the caller
    found = [r for r in records if str(r.get(match["field"])) == str(match["value"])]
    if not found:
        raise ValueError(f"no ATS record in {spec['path']} where {match['field']}={match['value']!r}")
    src = found[0]

    rec = empty_record()
    rec["full_name"] = src.get("applicant_name") or None
    if src.get("contact_email"):
        rec["emails"] = [src["contact_email"]]
    if src.get("mobile_number"):
        rec["phones"] = [src["mobile_number"]]
    rec["headline"] = src.get("current_role") or None
    rec["location_raw"] = src.get("city_country") or None
    rec["years_experience_raw"] = src.get("yrs_exp")

    for w in src.get("work_history", []) or []:
        rec["experience_raw"].append({
            "company": w.get("org"),
            "title": w.get("role"),
            "start": w.get("from"),
            "end": w.get("to"),
            "summary": w.get("desc"),
        })
    for q in src.get("qualifications", []) or []:
        rec["education_raw"].append({
            "institution": q.get("school"),
            "degree": q.get("degree_name"),
            "field": q.get("major"),
            "end_year": q.get("grad_year"),
        })
    rec["skills_raw"] = list(src.get("tag_list", []) or [])
    if src.get("linkedin_url"):
        rec["links_raw"]["linkedin"] = src["linkedin_url"]
    return rec


# ---- GitHub profile (unstructured #1) ----
# fixture mode reads a cached JSON file shaped like the real GitHub API --
# that's what default config + all the tests use, so results are
# deterministic. live mode actually hits the API (see below).
def extract_github(spec, base_dir):
    mode = spec.get("mode", "fixture")
    if mode == "fixture":
        path = _path(base_dir, spec["fixture_path"])
        with open(path, encoding="utf-8") as f:
            profile = json.load(f)
    else:
        username = spec["username"]
        profile = _fetch_github_live(username)
        if profile is None:
            raise ValueError(f"GitHub API unavailable or user not found: {username}")

    rec = empty_record()
    rec["full_name"] = profile.get("name") or None
    rec["headline"] = profile.get("bio") or None
    rec["location_raw"] = profile.get("location") or None
    rec["links_raw"]["github"] = profile.get("html_url")
    rec["links_raw"]["portfolio"] = profile.get("blog") or None

    languages = []
    for repo in profile.get("repos", []) or []:
        lang = repo.get("language")
        if lang and lang not in languages:
            languages.append(lang)
    rec["skills_raw"] = languages
    return rec


def _fetch_github_live(username):
    """Best-effort live fetch. Returns None on ANY failure -- never raises,
    never crashes the pipeline. Not exercised by the test suite (no network
    in CI); included to show the extractor interface is not fixture-only."""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/users/{username}",
            headers={"User-Agent": "eightfold-transformer"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            profile = json.loads(resp.read().decode("utf-8"))
        repos_req = urllib.request.Request(
            f"https://api.github.com/users/{username}/repos?per_page=100",
            headers={"User-Agent": "eightfold-transformer"},
        )
        with urllib.request.urlopen(repos_req, timeout=5) as resp:
            repos = json.loads(resp.read().decode("utf-8"))
        profile["repos"] = [{"name": r.get("name"), "language": r.get("language")} for r in repos]
        return profile
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError):
        return None


# ---- free-text recruiter notes (unstructured #2) ----
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
PHONE_RE = re.compile(r"(\+?\d[\d\-\s().]{6,}\d)")
YEARS_RE = re.compile(r"(\d+(?:\.\d+)?)\+?\s*(?:years|yrs)\b", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s,)]+")

# reuse the normalizer's alias dict instead of keeping a second skill list
# that would drift out of sync
from .normalizers import SKILL_ALIASES  # noqa: E402
NOTES_SKILL_VOCAB = sorted(SKILL_ALIASES.keys(), key=len, reverse=True)


def extract_notes(spec, base_dir):
    path = _path(base_dir, spec["path"])
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if not text.strip():
        raise ValueError(f"notes file {spec['path']} is empty")

    rec = empty_record()

    email_match = EMAIL_RE.search(text)
    if email_match:
        rec["emails"] = [email_match.group(0)]

    phone_match = re.search(r"phone[:\s]+" + PHONE_RE.pattern, text, re.IGNORECASE)
    if not phone_match:
        # no "Phone:" label -- fall back to a bare scan. Found a real bug
        # here during testing: without the label, this regex once grabbed
        # a date ("2026-05-12...") instead of the actual number. Left the
        # fallback in since it's still better than nothing, but it's the
        # noisier path -- normalize_phone() downstream will just reject it
        # if it isn't actually valid.
        phone_match = PHONE_RE.search(text)
    if phone_match:
        rec["phones"] = [phone_match.group(1).strip()]

    years_match = YEARS_RE.search(text)
    if years_match:
        rec["years_experience_raw"] = years_match.group(1)

    for line in text.splitlines():
        low = line.lower().strip()
        if low.startswith("title:") or low.startswith("current role:"):
            rec["headline"] = line.split(":", 1)[1].strip()
        elif low.startswith("location:"):
            rec["location_raw"] = line.split(":", 1)[1].strip()

    text_low = text.lower()
    found_skills = []
    for token in NOTES_SKILL_VOCAB:
        if re.search(r"(?<![\w.+#-])" + re.escape(token) + r"(?![\w.+#-])", text_low):
            if token not in found_skills:
                found_skills.append(token)
    rec["skills_raw"] = found_skills

    urls = URL_RE.findall(text)
    for u in urls:
        if "linkedin.com" in u:
            rec["links_raw"]["linkedin"] = u
        elif "github.com" in u:
            rec["links_raw"]["github"] = u
        else:
            rec["links_raw"]["other"].append(u)

    return rec


EXTRACTORS = {
    "csv": extract_csv,
    "ats_json": extract_ats_json,
    "github": extract_github,
    "notes": extract_notes,
}


def extract_source(spec, base_dir):
    """Returns (raw_record_or_None, source_type, error_message_or_None).
    Never raises -- every failure is converted into an error string so the
    pipeline can skip this source and keep going."""
    source_type = spec["type"]
    extractor = EXTRACTORS.get(source_type)
    if extractor is None:
        return None, source_type, f"unknown source type '{source_type}'"
    try:
        return extractor(spec, base_dir), source_type, None
    except FileNotFoundError as e:
        return None, source_type, f"source file not found: {e}"
    except json.JSONDecodeError as e:
        return None, source_type, f"source file is not valid JSON: {e}"
    except Exception as e:  # noqa: BLE001 - a bad source must never crash the run
        return None, source_type, f"{type(e).__name__}: {e}"
