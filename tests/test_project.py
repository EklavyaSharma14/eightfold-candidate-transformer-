import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from transformer.project import project, ProjectionError
from transformer.merge import merge_records, compute_overall_confidence
from transformer.extractors import empty_record


def _record_for(**kwargs):
    raw = empty_record()
    raw.update(kwargs)
    record = merge_records("X-1", [(raw, "ats_json")])
    record["overall_confidence"] = compute_overall_confidence(record)
    return record


def test_default_config_produces_expected_top_level_keys():
    record = _record_for(full_name="Asha Verma", emails=["a@example.com"])
    output = project(record)  # no config -> DEFAULT_CONFIG
    for key in ("candidate_id", "full_name", "emails", "phones", "location",
                "links", "headline", "years_experience", "skills",
                "experience", "education", "overall_confidence", "provenance"):
        assert key in output


def test_custom_config_can_rename_and_subset_fields():
    record = _record_for(full_name="Asha Verma", emails=["a@example.com"])
    cfg = {
        "fields": [
            {"path": "id", "from": "candidate_id", "type": "string"},
            {"path": "name", "from": "full_name", "type": "string"},
        ],
        "include_confidence": False,
        "include_provenance": False,
        "on_missing": "null",
    }
    output = project(record, cfg)
    assert output == {"id": "X-1", "name": "Asha Verma"}


def test_array_index_path_resolution():
    record = _record_for(emails=["a@example.com", "b@example.com"])
    cfg = {"fields": [{"path": "primary_email", "from": "emails[0]", "type": "string"}],
           "include_confidence": False, "include_provenance": False, "on_missing": "null"}
    output = project(record, cfg)
    assert output["primary_email"] == "a@example.com"


def test_flatten_path_resolution_over_object_list():
    record = _record_for(skills_raw=["python", "js"])
    cfg = {"fields": [{"path": "skill_names", "from": "skills[].name", "type": "string[]"}],
           "include_confidence": False, "include_provenance": False, "on_missing": "null"}
    output = project(record, cfg)
    assert set(output["skill_names"]) == {"Python", "JavaScript"}


def test_on_missing_null_fills_with_none():
    record = _record_for()  # nothing populated
    cfg = {"fields": [{"path": "headline", "from": "headline", "type": "string"}],
           "include_confidence": False, "include_provenance": False, "on_missing": "null"}
    output = project(record, cfg)
    assert output["headline"] is None


def test_on_missing_omit_drops_the_key():
    record = _record_for()
    cfg = {"fields": [{"path": "headline", "from": "headline", "type": "string"}],
           "include_confidence": False, "include_provenance": False, "on_missing": "omit"}
    output = project(record, cfg)
    assert "headline" not in output


def test_on_missing_error_raises_for_required_field():
    record = _record_for()  # no headline anywhere
    cfg = {"fields": [{"path": "headline", "from": "headline", "type": "string", "required": True}],
           "include_confidence": False, "include_provenance": False, "on_missing": "error"}
    try:
        project(record, cfg)
        assert False, "expected ProjectionError"
    except ProjectionError as e:
        assert "headline" in str(e)


def test_include_confidence_toggle_strips_skill_confidence_too():
    record = _record_for(skills_raw=["python"])
    cfg_on = {"fields": [{"path": "skills", "from": "skills", "type": "object[]"}],
              "include_confidence": True, "include_provenance": False, "on_missing": "null"}
    cfg_off = dict(cfg_on, include_confidence=False)

    out_on = project(record, cfg_on)
    out_off = project(record, cfg_off)

    assert "confidence" in out_on["skills"][0]
    assert "confidence" not in out_off["skills"][0]
    assert "overall_confidence" in out_on
    assert "overall_confidence" not in out_off


def test_national_normalize_override_changes_display_format():
    record = _record_for(phones=["4155550199"])
    cfg = {"fields": [{"path": "phone", "from": "phones[0]", "type": "string", "normalize": "national"}],
           "include_confidence": False, "include_provenance": False, "on_missing": "null"}
    output = project(record, cfg)
    assert output["phone"] != record["phones"]["value"][0]  # not the raw E.164 form
    assert "(" in output["phone"] or " " in output["phone"]  # some human-readable format
