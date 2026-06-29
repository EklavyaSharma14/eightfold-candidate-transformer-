import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from transformer import normalizers as norm


def test_phone_with_country_code_parses_cleanly():
    value, quality, note = norm.normalize_phone("+91 98765 43210")
    assert value == "+919876543210"
    assert quality == 1.0


def test_phone_without_country_code_uses_hint():
    value, quality, note = norm.normalize_phone("4155550199", region_hint="US")
    assert value == "+14155550199"
    assert quality == 1.0


def test_phone_without_country_code_or_hint_is_a_guess():
    value, quality, note = norm.normalize_phone("4155550199")
    assert value == "+14155550199"
    assert quality == 0.7  # flagged as a guess, not a clean parse


def test_garbage_phone_never_invents_a_value():
    value, quality, note = norm.normalize_phone("not-a-phone-number")
    assert value is None
    assert quality == 0.0


def test_date_full_iso_passes_through():
    value, quality, note, is_current = norm.normalize_date("2021-03-15")
    assert value == "2021-03"


def test_date_year_only_is_flagged_low_precision():
    value, quality, note, is_current = norm.normalize_date("2019")
    assert value == "2019-01"
    assert quality < 1.0
    assert "month unknown" in note


def test_date_present_marker_is_open_ended():
    value, quality, note, is_current = norm.normalize_date("Present")
    assert value is None
    assert is_current is True
    assert quality == 1.0  # "present" is unambiguous, not a low-confidence guess


def test_unparseable_date_returns_none_not_a_guess():
    value, quality, note, is_current = norm.normalize_date("sometime last spring-ish")
    assert value is None
    assert quality == 0.0


def test_country_alias():
    code, quality, note = norm.normalize_country("USA")
    assert code == "US"
    assert quality == 1.0


def test_country_already_iso2():
    code, quality, note = norm.normalize_country("IN")
    assert code == "IN"


def test_unrecognized_country_returns_none():
    code, quality, note = norm.normalize_country("Atlantis")
    assert code is None
    assert quality == 0.0


def test_skill_alias_canonicalization():
    name, quality, note = norm.canonical_skill("js")
    assert name == "JavaScript"
    assert quality == 1.0

    name, quality, note = norm.canonical_skill("ReactJS")
    assert name == "React"


def test_unknown_skill_is_kept_but_flagged_lower_quality():
    name, quality, note = norm.canonical_skill("FooBarLang")
    assert name == "FooBarLang"
    assert quality < 1.0


def test_name_normalization_does_not_recase():
    value, quality, note = norm.normalize_name("  McKinsey   O'Brien ")
    assert value == "McKinsey O'Brien"  # whitespace fixed, case untouched
