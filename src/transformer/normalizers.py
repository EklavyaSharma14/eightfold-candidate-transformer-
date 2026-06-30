"""
Per-field normalizers. Each one returns (value, quality, note):
value is None if we can't confidently produce one (never guess/invent),
quality is 0-1 for how clean the parse was, note explains what happened
(goes into provenance later).
"""
import re
import phonenumbers
from dateutil import parser as dateutil_parser
import pycountry

# ---- phone numbers -> E.164 ----
DEFAULT_REGION = "US"  # only used as a last-resort fallback

def normalize_phone(raw, region_hint=None):
    if not raw or not str(raw).strip():
        return None, 0.0, "empty phone"

    raw = str(raw).strip()
    digits_plus = re.sub(r"[^\d+]", "", raw)
    if not digits_plus:
        return None, 0.0, f"no digits found in '{raw}'"

    quality = 1.0
    regions_to_try = []
    if digits_plus.startswith("+"):
        regions_to_try = [None]  # phonenumbers infers region from the + prefix
    else:
        if region_hint:
            regions_to_try = [region_hint]
        else:
            # no country code and nothing to guess from -> still try, but
            # don't pretend this is a clean parse
            regions_to_try = [DEFAULT_REGION]
            quality = 0.7

    for region in regions_to_try:
        try:
            parsed = phonenumbers.parse(digits_plus, region)
        except phonenumbers.NumberParseException:
            continue
        if phonenumbers.is_valid_number(parsed):
            e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
            note = "parsed cleanly" if quality == 1.0 else f"no country code given; assumed region={region}"
            return e164, quality, note

    return None, 0.0, f"could not parse '{raw}' as a valid phone number"


def to_national_display(e164_value):
    """Used only when a runtime config explicitly asks for a display/national format."""
    if not e164_value:
        return None
    try:
        parsed = phonenumbers.parse(e164_value, None)
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
    except phonenumbers.NumberParseException:
        return e164_value


# ---- dates -> YYYY-MM ----
CURRENT_MARKERS = {"present", "current", "now", "ongoing", "till date", "to date"}

def normalize_date(raw):
    """(value, quality, note, is_current)"""
    if raw is None:
        return None, 0.0, "missing date", False
    s = str(raw).strip()
    if not s:
        return None, 0.0, "empty date", False
    if s.lower() in CURRENT_MARKERS:
        return None, 1.0, "open-ended / still current", True

    # just a year, e.g. "2019" -- don't pretend we know the month
    if re.fullmatch(r"(19|20)\d{2}", s):
        return f"{s}-01", 0.6, "year only; month unknown, defaulted to 01", False

    if re.fullmatch(r"(19|20)\d{2}-\d{2}", s):
        return s, 1.0, "already YYYY-MM", False

    try:
        dt = dateutil_parser.parse(s, default=dateutil_parser.parse("2000-01-01"))
        return dt.strftime("%Y-%m"), 1.0, f"parsed '{s}'", False
    except (ValueError, OverflowError):
        return None, 0.0, f"could not parse date '{s}'", False


# ---- country -> ISO 3166-1 alpha-2 ----
COUNTRY_ALIASES = {
    "usa": "US", "u.s.a.": "US", "us": "US", "united states": "US",
    "united states of america": "US",
    "uk": "GB", "u.k.": "GB", "united kingdom": "GB", "england": "GB",
    "india": "IN", "bharat": "IN",
    "uae": "AE", "united arab emirates": "AE",
    "south korea": "KR", "korea": "KR",
}

def normalize_country(raw):
    if not raw or not str(raw).strip():
        return None, 0.0, "missing country"
    s = str(raw).strip()
    key = s.lower()

    if key in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[key], 1.0, f"alias match for '{s}'"

    if re.fullmatch(r"[A-Za-z]{2}", s):
        code = s.upper()
        if pycountry.countries.get(alpha_2=code):
            return code, 1.0, "already ISO alpha-2"

    try:
        match = pycountry.countries.search_fuzzy(s)
        if match:
            return match[0].alpha_2, 0.85, f"fuzzy matched '{s}'"
    except LookupError:
        pass

    return None, 0.0, f"unrecognized country '{s}'"


# ---- skills -> canonical name ----
SKILL_ALIASES = {
    "js": "JavaScript", "javascript": "JavaScript", "node": "Node.js",
    "node.js": "Node.js", "nodejs": "Node.js",
    "py": "Python", "python": "Python", "python3": "Python",
    "react": "React", "reactjs": "React", "react.js": "React",
    "ts": "TypeScript", "typescript": "TypeScript",
    "golang": "Go", "go": "Go",
    "k8s": "Kubernetes", "kubernetes": "Kubernetes",
    "postgres": "PostgreSQL", "postgresql": "PostgreSQL",
    "ml": "Machine Learning", "machine learning": "Machine Learning",
    "aws": "AWS", "amazon web services": "AWS",
    "html": "HTML", "css": "CSS", "html5": "HTML", "css3": "CSS",
    "java": "Java", "c++": "C++", "cpp": "C++", "c#": "C#", "csharp": "C#",
    "sql": "SQL", "docker": "Docker", "graphql": "GraphQL",
    "django": "Django", "flask": "Flask", "rest api": "REST APIs",
    "rest apis": "REST APIs", "git": "Git",
}

def canonical_skill(raw):
    if not raw or not str(raw).strip():
        return None, 0.0, "empty skill"
    key = str(raw).strip().lower()
    if key in SKILL_ALIASES:
        return SKILL_ALIASES[key], 1.0, f"alias match for '{raw}'"
    # Unknown skill: keep as-is (light cleanup only), but flag lower quality
    # since we have no dictionary confirmation it's a real/standard skill name.
    cleaned = str(raw).strip()
    return cleaned, 0.6, f"no canonical alias for '{raw}'; used as-is"


# ---- names / free text -- trim + collapse whitespace, don't re-case ----
# (titlecasing breaks real names like "O'Brien" or "McDonald", so leave
# case exactly as given)
def normalize_name(raw):
    if not raw or not str(raw).strip():
        return None, 0.0, "empty name"
    cleaned = re.sub(r"\s+", " ", str(raw).strip())
    return cleaned, 1.0, "trimmed/whitespace-collapsed; case preserved as given"


def normalize_email(raw):
    if not raw or not str(raw).strip():
        return None, 0.0, "empty email"
    s = str(raw).strip().lower()
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", s):
        return s, 1.0, "looks like a valid email"
    return None, 0.0, f"does not look like a valid email: '{raw}'"
