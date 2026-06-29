import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from transformer.merge import merge_records, compute_overall_confidence
from transformer.extractors import empty_record


def _raw(**kwargs):
    rec = empty_record()
    rec.update(kwargs)
    return rec


def test_agreeing_sources_boost_confidence_above_either_alone():
    # Two sources giving the SAME headline should score higher than if
    # only the stronger one had it.
    raw_csv = _raw(headline="Senior Backend Engineer")
    raw_ats = _raw(headline="Senior Backend Engineer")
    merged_both = merge_records("X", [(raw_csv, "csv"), (raw_ats, "ats_json")])

    merged_ats_only = merge_records("X", [(raw_ats, "ats_json")])

    assert merged_both["headline"]["confidence"] > merged_ats_only["headline"]["confidence"]
    assert merged_both["headline"]["value"] == "Senior Backend Engineer"


def test_conflicting_sources_pick_higher_priority_and_lose_confidence():
    raw_ats = _raw(headline="Senior Software Engineer")     # ats_json: high priority
    raw_notes = _raw(headline="Software Engineer II")        # notes: low priority

    merged = merge_records("X", [(raw_ats, "ats_json"), (raw_notes, "notes")])
    merged_ats_only = merge_records("X", [(raw_ats, "ats_json")])

    assert merged["headline"]["value"] == "Senior Software Engineer"  # ats_json wins
    # Conflict should cost some confidence vs. having no disagreement at all.
    assert merged["headline"]["confidence"] < merged_ats_only["headline"]["confidence"]

    # The losing value must still be recoverable from provenance -- we
    # never just silently throw away what a lower-priority source said.
    lost = [p for p in merged["provenance"] if p["field"] == "headline" and p["source"] == "notes"]
    assert lost and lost[0]["method"] == "merged:overridden"


def test_phones_and_emails_are_unioned_not_winner_take_all():
    raw_a = _raw(emails=["a@example.com"])
    raw_b = _raw(emails=["b@example.com"])
    merged = merge_records("X", [(raw_a, "csv"), (raw_b, "ats_json")])
    assert sorted(merged["emails"]["value"]) == ["a@example.com", "b@example.com"]


def test_skills_canonicalize_and_merge_aliases_into_one_entry():
    raw_a = _raw(skills_raw=["js", "py"])
    raw_b = _raw(skills_raw=["JavaScript", "Python"])
    merged = merge_records("X", [(raw_a, "notes"), (raw_b, "github")])
    names = {s["name"] for s in merged["skills"]}
    assert names == {"JavaScript", "Python"}
    js = next(s for s in merged["skills"] if s["name"] == "JavaScript")
    assert sorted(js["sources"]) == ["github", "notes"]


def test_garbage_source_never_invents_a_phone():
    raw = _raw(phones=["this is not a phone number"])
    merged = merge_records("X", [(raw, "notes")])
    assert merged["phones"]["value"] == []
    failed = [p for p in merged["provenance"] if p["field"] == "phones" and p["method"] == "normalize:failed"]
    assert failed


def test_overall_confidence_is_lower_for_a_thinner_profile():
    rich = _raw(
        full_name="Asha Verma", emails=["a@example.com"], phones=["+919876543210"],
        headline="Engineer", years_experience_raw=5, skills_raw=["python"],
    )
    thin = _raw(full_name="Asha Verma")

    rich_record = merge_records("X", [(rich, "ats_json")])
    rich_record["overall_confidence"] = compute_overall_confidence(rich_record)

    thin_record = merge_records("X", [(thin, "csv")])
    thin_record["overall_confidence"] = compute_overall_confidence(thin_record)

    assert thin_record["overall_confidence"] < rich_record["overall_confidence"]


def test_us_state_abbreviation_is_not_mistaken_for_a_country():
    raw = _raw(location_raw="San Francisco, CA")
    merged = merge_records("X", [(raw, "csv")])
    loc = merged["location"]["value"]
    assert loc["country"] == "US"   # not "CA" misread as Canada
    assert loc["region"] == "CA"
