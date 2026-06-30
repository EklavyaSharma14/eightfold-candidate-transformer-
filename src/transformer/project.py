"""
Reshapes the canonical record into whatever output shape was asked for.

DEFAULT_CONFIG below is just the assignment's default schema written as a
config -- it goes through the exact same project() function as any custom
config someone passes in. No special-casing, which is the point: it's how
a custom config can change the output without touching this file at all.
"""
import re
from . import normalizers as norm

DEFAULT_CONFIG = {
    "fields": [
        {"path": "candidate_id", "from": "candidate_id", "type": "string", "required": True},
        {"path": "full_name", "from": "full_name", "type": "string", "required": True},
        {"path": "emails", "from": "emails", "type": "string[]"},
        {"path": "phones", "from": "phones", "type": "string[]", "normalize": "E164"},
        {"path": "location", "from": "location", "type": "object"},
        {"path": "links", "from": "links", "type": "object"},
        {"path": "headline", "from": "headline", "type": "string"},
        {"path": "years_experience", "from": "years_experience", "type": "number"},
        {"path": "skills", "from": "skills", "type": "object[]", "normalize": "canonical"},
        {"path": "experience", "from": "experience", "type": "object[]"},
        {"path": "education", "from": "education", "type": "object[]"},
    ],
    "include_confidence": True,
    "include_provenance": True,
    "on_missing": "null",
}

WRAPPED_SCALAR_FIELDS = {"full_name", "emails", "phones", "location", "headline", "years_experience"}


class ProjectionError(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(errors))


def build_values_view(record):
    """Flatten the internal {value, confidence}-wrapped canonical record
    into a plain dict shaped like the public schema."""
    return {
        "candidate_id": record["candidate_id"],
        "full_name": record["full_name"]["value"],
        "emails": record["emails"]["value"],
        "phones": record["phones"]["value"],
        "location": record["location"]["value"],
        "headline": record["headline"]["value"],
        "years_experience": record["years_experience"]["value"],
        "skills": record["skills"],
        "experience": [
            {"company": e["company"], "title": e["title"], "start": e["start"],
             "end": e["end"], "summary": e["summary"]}
            for e in record["experience"]
        ],
        "education": [
            {"institution": e["institution"], "degree": e["degree"],
             "field": e["field"], "end_year": e["end_year"]}
            for e in record["education"]
        ],
        "links": record["links"],
        "provenance": record["provenance"],
        "overall_confidence": record.get("overall_confidence"),
        "source_errors": record.get("source_errors", []),
    }


_SEGMENT_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)(\[(\d*)\])?$")


def _resolve_segments(value, segments):
    if not segments:
        return value
    seg, rest = segments[0], segments[1:]
    m = _SEGMENT_RE.match(seg)
    if not m:
        return None
    key, has_brackets, idx = m.group(1), m.group(2), m.group(3)
    if not isinstance(value, dict) or key not in value:
        return None
    value = value[key]
    if not has_brackets:
        return _resolve_segments(value, rest) if rest else value
    if not isinstance(value, list):
        return None
    if idx == "":  # "field[]" -> map remaining path over every item
        return [_resolve_segments(item, rest) for item in value] if rest else value
    i = int(idx)
    if i >= len(value):
        return None
    item = value[i]
    return _resolve_segments(item, rest) if rest else item


def resolve_path(values_view, record, path):
    """Resolve a 'from' path against the flattened values view, with one
    special case: '<field>.confidence' reaches into the wrapped scalar
    fields' confidence score directly, since that confidence lives
    alongside -- not inside -- the plain value in our internal model."""
    if "." in path:
        head, tail = path.split(".", 1)
        if tail == "confidence" and head in WRAPPED_SCALAR_FIELDS:
            return record[head]["confidence"]
    return _resolve_segments(values_view, path.split("."))


def _coerce_type(value, type_, errors, out_key):
    if value is None or type_ is None:
        return value
    try:
        if type_ == "string":
            return str(value)
        if type_ == "number":
            return value if isinstance(value, (int, float)) else float(value)
        if type_ == "boolean":
            return bool(value)
        if type_ == "string[]":
            if not isinstance(value, list):
                raise TypeError
            return [str(v) for v in value]
        if type_ in ("object", "object[]"):
            return value  # structural passthrough
    except (TypeError, ValueError):
        errors.append(f"field '{out_key}': expected type {type_}, got {type(value).__name__}")
        return value
    return value


def project(record, config=None):
    """Apply a runtime config to the canonical record. Returns the
    projected output dict, or raises ProjectionError for required-missing
    (when on_missing='error') or type problems."""
    cfg = config or DEFAULT_CONFIG
    values_view = build_values_view(record)
    on_missing = cfg.get("on_missing", "null")
    errors = []
    output = {}

    for spec in cfg["fields"]:
        out_key = spec["path"]
        from_path = spec.get("from", out_key)
        value = resolve_path(values_view, record, from_path)
        is_missing = value is None

        if is_missing:
            if on_missing == "omit":
                continue
            if on_missing == "error" and spec.get("required", False):
                errors.append(f"required field '{out_key}' (from '{from_path}') is missing")
                continue
            output[out_key] = None
            continue

        normalize = spec.get("normalize")
        if normalize == "national":
            value = [norm.to_national_display(v) for v in value] if isinstance(value, list) else norm.to_national_display(value)
        # "E164" and "canonical" are no-ops at projection time: the
        # canonical record already stores phones as E.164 and skills
        # under their canonical name, so the override is a no-op
        # confirmation rather than a real re-normalization.

        output[out_key] = _coerce_type(value, spec.get("type"), errors, out_key)

    if errors:
        raise ProjectionError(errors)

    if cfg.get("include_confidence", True):
        output["overall_confidence"] = record.get("overall_confidence")
        if "skills" in output and isinstance(output["skills"], list):
            pass  # keep per-skill confidence
    else:
        output.pop("overall_confidence", None)
        if "skills" in output and isinstance(output["skills"], list):
            output["skills"] = [{k: v for k, v in s.items() if k != "confidence"} for s in output["skills"]]

    if cfg.get("include_provenance", True):
        output["provenance"] = record.get("provenance", [])
        output["source_errors"] = record.get("source_errors", [])
    else:
        output.pop("provenance", None)

    return output
