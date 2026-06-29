import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from transformer.pipeline import run_pipeline

ROOT = os.path.join(os.path.dirname(__file__), "..")
MANIFEST = os.path.join(ROOT, "data", "manifest.json")
CUSTOM_CONFIG = os.path.join(ROOT, "configs", "recruiter_lite.json")


def _by_id(results, candidate_id):
    for r in results:
        if r.get("candidate_id") == candidate_id or r.get("id") == candidate_id:
            return r
    raise KeyError(candidate_id)


def test_pipeline_runs_end_to_end_on_default_schema():
    result = run_pipeline(MANIFEST, base_dir=ROOT)
    assert len(result["results"]) == 3
    c1 = _by_id(result["results"], "C-1001")
    assert c1["full_name"] == "Asha Verma"
    assert "+919876543210" in c1["phones"]
    assert any(s["name"] == "Python" for s in c1["skills"])
    assert c1["overall_confidence"] > 0.8  # clean, agreeing, multi-source profile


def test_pipeline_resolves_a_real_cross_source_conflict():
    """Gold-profile check: ATS says 'Senior Software Engineer', CSV+notes
    both (independently) say 'Software Engineer II'. ATS must win on
    priority even though two lower-priority sources agree with each other --
    majority vote among weak sources should not beat one strong source."""
    result = run_pipeline(MANIFEST, base_dir=ROOT)
    c2 = _by_id(result["results"], "C-1002")
    assert c2["headline"] == "Senior Software Engineer"


def test_pipeline_degrades_gracefully_on_missing_and_garbage_sources():
    """Candidate 3: malformed ATS JSON, a GitHub fixture that doesn't
    exist on disk, and an empty notes file. The pipeline must not crash,
    must still return a profile built from whatever survived (the CSV),
    and that profile's confidence must visibly reflect the gap."""
    result = run_pipeline(MANIFEST, base_dir=ROOT)
    assert result["results"], "pipeline must not crash on a batch with bad sources"

    c3 = _by_id(result["results"], "C-1003")
    assert "error" not in c3  # default config has on_missing=null, no required-field crash
    assert c3["full_name"] == "Priya Nair"          # survived from CSV
    assert c3["skills"] == []                       # no skills source survived
    assert c3["education"] == []                    # no education source survived

    c1 = _by_id(result["results"], "C-1001")
    assert c3["overall_confidence"] < c1["overall_confidence"]


def test_custom_config_error_mode_fails_only_the_affected_candidate():
    """recruiter_lite.json requires years_experience with on_missing=error.
    Candidates 1 and 2 have it (from ATS); candidate 3's only surviving
    source (CSV) never carried it. The batch must still return all three
    candidates -- one error record, two normal ones -- not crash entirely."""
    result = run_pipeline(MANIFEST, CUSTOM_CONFIG, base_dir=ROOT)
    assert len(result["results"]) == 3

    c1 = _by_id(result["results"], "C-1001")
    assert "error" not in c1
    assert c1["years_experience"] == 6.5

    c3 = _by_id(result["results"], "C-1003")
    assert "error" in c3
    assert "years_experience" in c3["error"]
    assert any("C-1003" in e for e in result["run_errors"])


def test_provenance_traces_every_populated_field_to_a_source():
    result = run_pipeline(MANIFEST, base_dir=ROOT)
    c1 = _by_id(result["results"], "C-1001")
    fields_with_provenance = {p["field"] for p in c1["provenance"]}
    for field in ("full_name", "emails", "phones", "headline", "skills"):
        assert field in fields_with_provenance
