"""
Merge stage: takes the raw records pulled from each source for one
candidate, normalizes every value, and merges them into a single canonical
record with per-field confidence and a full provenance trail.

Scalar fields (full_name, headline, years_experience, location) are
winner-take-all: every source's normalized value is scored, the highest
score wins, and the rest are kept in provenance as "lost" alternatives.

List fields (emails, phones, skills, experience, education) are unioned and
deduplicated -- a candidate legitimately can have two emails, but can't
have two "true" current titles.
"""
import re
from . import normalizers as norm
from .source_priority import weight_for

# 2-letter US state codes collide with real ISO country codes (CA=Canada,
# IN=India, ...). A location string like "San Francisco, CA" means
# California, not Canada -- catch that BEFORE handing the token to the
# country normalizer, which would otherwise confidently return the wrong
# country. This is exactly the "wrong-but-confident" failure mode the brief
# warns about, so it gets a dedicated (lower-confidence, clearly-noted) path
# rather than silent misuse of normalize_country.
US_STATE_ABBR = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}


def _looks_like_us_state_abbr(token):
    return bool(re.fullmatch(r"[A-Za-z]{2}", token.strip())) and token.strip().upper() in US_STATE_ABBR

CANONICAL_FIELDS = [
    "full_name", "emails", "phones", "location", "headline",
    "years_experience", "skills", "experience", "education", "links",
]


def _new_canonical(candidate_id):
    return {
        "candidate_id": candidate_id,
        "full_name": {"value": None, "confidence": 0.0},
        "emails": {"value": [], "confidence": 0.0},
        "phones": {"value": [], "confidence": 0.0},
        "location": {"value": {"city": None, "region": None, "country": None}, "confidence": 0.0},
        "headline": {"value": None, "confidence": 0.0},
        "years_experience": {"value": None, "confidence": 0.0},
        "skills": [],      # [{name, confidence, sources:[...]}]
        "experience": [],  # [{company,title,start,end,summary, _confidence, _sources}]
        "education": [],   # [{institution,degree,field,end_year, _confidence, _sources}]
        "links": {"linkedin": None, "github": None, "portfolio": None, "other": []},
        "provenance": [],
        "source_errors": [],
    }


def _add_provenance(record, field, source, method, raw_value=None, note=""):
    record["provenance"].append({
        "field": field, "source": source, "method": method,
        "raw_value": raw_value, "note": note,
    })


def _parse_location_string(raw):
    """Best-effort 'City, Region, Country' or 'City, Country' splitter."""
    if not raw:
        return None, None, None
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    if not parts:
        return None, None, None
    if len(parts) == 1:
        return None, None, parts[0]
    if len(parts) == 2:
        return parts[0], None, parts[1]
    return parts[0], parts[1], parts[2]


def merge_records(candidate_id, extracted):
    """
    extracted: list of (raw_record, source_type) for sources that were
    successfully extracted, plus the caller is expected to have already
    logged any source_errors separately (passed in via record afterwards).
    """
    record = _new_canonical(candidate_id)

    # ---- scalar: full_name --------------------------------------------
    candidates = []
    for raw, source in extracted:
        if raw.get("full_name"):
            value, quality, note = norm.normalize_name(raw["full_name"])
            if value:
                score = weight_for("full_name", source) * quality
                candidates.append((score, value, source, raw["full_name"], note))
    _resolve_scalar(record, "full_name", candidates)

    # ---- list: emails ----------------------------------------------------
    email_candidates = []
    for raw, source in extracted:
        for e in raw.get("emails", []):
            value, quality, note = norm.normalize_email(e)
            if value:
                score = weight_for("emails", source) * quality
                email_candidates.append((score, value, source, e, note))
    _resolve_list(record, "emails", email_candidates)

    # ---- list: phones ------------------------------------------------
    phone_candidates = []
    for raw, source in extracted:
        # use this source's own location as a region hint if we have one
        _, _, country_hint = _parse_location_string(raw.get("location_raw"))
        region_hint = None
        if country_hint:
            code, _, _ = norm.normalize_country(country_hint)
            region_hint = code
        for p in raw.get("phones", []):
            value, quality, note = norm.normalize_phone(p, region_hint=region_hint)
            if value:
                score = weight_for("phones", source) * quality
                phone_candidates.append((score, value, source, p, note))
            else:
                _add_provenance(record, "phones", source, "normalize:failed", p, note)
    _resolve_list(record, "phones", phone_candidates)

    # ---- scalar-ish: location -----------------------------------------
    loc_candidates = []
    for raw, source in extracted:
        if raw.get("location_raw"):
            city, region, country_raw = _parse_location_string(raw["location_raw"])
            if country_raw and region is None and _looks_like_us_state_abbr(country_raw):
                # "City, CA" pattern: that's a US state, not the country "CA" (Canada).
                region = country_raw.upper()
                country, c_quality, c_note = "US", 0.7, f"'{country_raw}' read as a US state abbreviation, not a country code"
            elif country_raw:
                country, c_quality, c_note = norm.normalize_country(country_raw)
            else:
                country, c_quality, c_note = None, 0.0, "no country token"
            quality = c_quality if country else 0.3  # partial credit for city/region even with no resolvable country
            score = weight_for("location", source) * quality
            loc_value = {"city": city, "region": region, "country": country}
            loc_candidates.append((score, loc_value, source, raw["location_raw"], c_note))
    _resolve_scalar(record, "location", loc_candidates, is_object=True)

    # ---- scalar: headline ----------------------------------------------
    headline_candidates = []
    for raw, source in extracted:
        if raw.get("headline"):
            value, quality, note = norm.normalize_name(raw["headline"])
            if value:
                score = weight_for("headline", source) * quality
                headline_candidates.append((score, value, source, raw["headline"], note))
    _resolve_scalar(record, "headline", headline_candidates)

    # ---- scalar: years_experience --------------------------------------
    years_candidates = []
    for raw, source in extracted:
        raw_years = raw.get("years_experience_raw")
        if raw_years is not None:
            try:
                value = float(raw_years)
                score = weight_for("years_experience", source) * 1.0
                years_candidates.append((score, value, source, raw_years, "parsed as number"))
            except (TypeError, ValueError):
                _add_provenance(record, "years_experience", source, "normalize:failed", raw_years, "not numeric")
    _resolve_scalar(record, "years_experience", years_candidates)

    # ---- skills (union + canonicalize) ---------------------------------
    skill_map = {}  # canonical_name -> {"confidence":..., "sources": set()}
    for raw, source in extracted:
        for s in raw.get("skills_raw", []):
            value, quality, note = norm.canonical_skill(s)
            if not value:
                continue
            score = weight_for("skills", source) * quality
            entry = skill_map.setdefault(value, {"score": 0.0, "sources": set(), "agree_count": 0})
            entry["agree_count"] += 1
            entry["sources"].add(source)
            entry["score"] = max(entry["score"], score)
            _add_provenance(record, "skills", source, f"canonicalized:{note}", s)
    for name, info in skill_map.items():
        conf = info["score"]
        if info["agree_count"] > 1:
            conf = min(1.0, conf + 0.15 * (info["agree_count"] - 1))
        record["skills"].append({
            "name": name,
            "confidence": round(conf, 2),
            "sources": sorted(info["sources"]),
        })
    record["skills"].sort(key=lambda s: (-s["confidence"], s["name"]))

    # ---- experience (dedupe by company+title, prefer highest-weight) ---
    exp_map = {}
    for raw, source in extracted:
        for item in raw.get("experience_raw", []):
            company = item.get("company")
            title = item.get("title")
            if not company and not title:
                continue
            key = ((company or "").strip().lower(), (title or "").strip().lower())
            start_v, start_q, start_note = norm.normalize_date(item.get("start"))[:3] if item.get("start") else (None, 0.0, "")
            end_parsed = norm.normalize_date(item.get("end")) if item.get("end") else (None, 1.0, "no end date given", False)
            end_v, end_q, end_note, is_current = end_parsed
            score = weight_for("experience", source) * 1.0
            existing = exp_map.get(key)
            candidate_item = {
                "company": company, "title": title,
                "start": start_v, "end": end_v, "summary": item.get("summary"),
                "_confidence": round(score, 2), "_sources": {source},
                "_is_current": is_current,
            }
            if existing is None or score > existing["_score"]:
                candidate_item["_score"] = score
                if existing is not None:
                    candidate_item["_sources"] |= existing["_sources"]
                exp_map[key] = candidate_item
            else:
                existing["_sources"].add(source)
            _add_provenance(record, "experience", source,
                             "merged:priority" if existing else "extracted",
                             {"company": company, "title": title}, "")
    for item in exp_map.values():
        item["_sources"] = sorted(item["_sources"])
        item.pop("_score", None)
        record["experience"].append(item)

    # ---- education (dedupe by institution+degree) -----------------------
    edu_map = {}
    for raw, source in extracted:
        for item in raw.get("education_raw", []):
            institution = item.get("institution")
            if not institution:
                continue
            key = (institution.strip().lower(), (item.get("degree") or "").strip().lower())
            score = weight_for("education", source) * 1.0
            candidate_item = {
                "institution": institution, "degree": item.get("degree"),
                "field": item.get("field"), "end_year": item.get("end_year"),
                "_confidence": round(score, 2), "_sources": {source},
            }
            existing = edu_map.get(key)
            if existing is None or score > existing["_score"]:
                candidate_item["_score"] = score
                if existing is not None:
                    candidate_item["_sources"] |= existing["_sources"]
                edu_map[key] = candidate_item
            else:
                existing["_sources"].add(source)
            _add_provenance(record, "education", source, "extracted",
                             {"institution": institution}, "")
    for item in edu_map.values():
        item["_sources"] = sorted(item["_sources"])
        item.pop("_score", None)
        record["education"].append(item)

    # ---- links (direct, no real "conflict" -- different slots) ---------
    for raw, source in extracted:
        links = raw.get("links_raw", {})
        if links.get("github") and not record["links"]["github"]:
            record["links"]["github"] = links["github"]
            _add_provenance(record, "links.github", source, "direct", links["github"])
        if links.get("linkedin") and not record["links"]["linkedin"]:
            record["links"]["linkedin"] = links["linkedin"]
            _add_provenance(record, "links.linkedin", source, "direct", links["linkedin"])
        if links.get("portfolio") and not record["links"]["portfolio"]:
            record["links"]["portfolio"] = links["portfolio"]
            _add_provenance(record, "links.portfolio", source, "direct", links["portfolio"])
        for other in links.get("other", []):
            if other not in record["links"]["other"]:
                record["links"]["other"].append(other)

    return record


def _resolve_scalar(record, field, candidates, is_object=False):
    if not candidates:
        return
    candidates.sort(key=lambda c: -c[0])
    winner_score, winner_value, winner_source, winner_raw, winner_note = candidates[0]

    agree_bonus = 0.0
    if len(candidates) > 1:
        same_value = [c for c in candidates[1:] if c[1] == winner_value]
        agree_bonus = 0.15 * len(same_value)
        for c in candidates[1:]:
            if c[1] != winner_value:
                _add_provenance(record, field, c[2], "merged:overridden", c[3],
                                 f"lost to higher-priority source ({winner_source}); kept here for audit")
    conflict_penalty = 0.0 if (len(candidates) == 1 or all(c[1] == winner_value for c in candidates[1:])) else 0.15

    final_conf = max(0.0, min(1.0, winner_score + agree_bonus - conflict_penalty))
    record[field]["value"] = winner_value
    record[field]["confidence"] = round(final_conf, 2)
    _add_provenance(record, field, winner_source, "merged:winner" if len(candidates) > 1 else "direct",
                     winner_raw, winner_note)


def compute_overall_confidence(record):
    """Sum of populated-field confidences / a FIXED number of fields.
    A thin profile is scored low, not inflated just because the few
    fields it does have happen to be confident."""
    terms = [
        record["full_name"]["confidence"],
        record["emails"]["confidence"] if record["emails"]["value"] else 0.0,
        record["phones"]["confidence"] if record["phones"]["value"] else 0.0,
        record["location"]["confidence"],
        record["headline"]["confidence"],
        record["years_experience"]["confidence"],
        (sum(s["confidence"] for s in record["skills"]) / len(record["skills"])) if record["skills"] else 0.0,
        (sum(e["_confidence"] for e in record["experience"]) / len(record["experience"])) if record["experience"] else 0.0,
        (sum(e["_confidence"] for e in record["education"]) / len(record["education"])) if record["education"] else 0.0,
    ]
    return round(sum(terms) / len(terms), 2)


def _resolve_list(record, field, candidates):
    if not candidates:
        return
    seen = {}
    for score, value, source, raw, note in candidates:
        entry = seen.setdefault(value, {"score": 0.0, "sources": set()})
        entry["score"] = max(entry["score"], score)
        entry["sources"].add(source)
    values = sorted(seen.keys())
    record[field]["value"] = values
    confs = []
    for v, info in seen.items():
        boosted = info["score"]
        if len(info["sources"]) > 1:
            boosted = min(1.0, boosted + 0.15 * (len(info["sources"]) - 1))
        confs.append(boosted)
    record[field]["confidence"] = round(sum(confs) / len(confs), 2) if confs else 0.0
    for score, value, source, raw, note in candidates:
        _add_provenance(record, field, source, "merged:union", raw, note)
