"""
Wires everything together. run_pipeline() takes a manifest + optional
config and runs detect -> extract -> normalize -> merge -> confidence ->
project -> validate for every candidate in it.

One candidate failing (bad config, every source broken, etc) doesn't take
the rest of the batch down with it -- that's the whole point of catching
errors this granularly instead of just wrapping the loop in one big
try/except.
"""
import json
import os

from .extractors import extract_source
from .merge import merge_records, compute_overall_confidence
from .project import project, ProjectionError, DEFAULT_CONFIG
from .validate import validate_config, validate_output


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_canonical_record(candidate_id, sources, base_dir):
    """Runs detect -> extract -> normalize -> merge -> confidence for one
    candidate. Always returns a record, even if every source failed."""
    extracted = []
    source_errors = []

    for spec in sources:
        raw, source_type, error = extract_source(spec, base_dir)
        if error:
            source_errors.append({"source": source_type, "spec": spec, "error": error})
            continue
        extracted.append((raw, source_type))

    record = merge_records(candidate_id, extracted)
    record["source_errors"] = source_errors
    record["overall_confidence"] = compute_overall_confidence(record)
    return record


def run_pipeline(manifest_path, config_path=None, base_dir=None):
    """Returns {"results": [...], "run_errors": [...]}.

    results[i] is either a successfully projected+validated candidate
    profile, or an {"candidate_id":..., "error": "..."} record if that
    one candidate couldn't be produced under the requested config
    (e.g. on_missing='error' and a required field really is missing).
    """
    manifest = load_json(manifest_path)
    base_dir = base_dir or os.getcwd()

    config = DEFAULT_CONFIG
    if config_path:
        config = load_json(config_path)
        config_errors = validate_config(config)
        if config_errors:
            return {"results": [], "run_errors": [f"invalid config: {e}" for e in config_errors]}

    results = []
    run_errors = []

    for entry in manifest.get("candidates", []):
        candidate_id = entry["candidate_id"]
        try:
            record = build_canonical_record(candidate_id, entry.get("sources", []), base_dir)
            output = project(record, config)
            shape_errors = validate_output(output, config)
            if shape_errors:
                results.append({"candidate_id": candidate_id, "error": "; ".join(shape_errors)})
                run_errors.append(f"{candidate_id}: output failed shape validation")
                continue
            results.append(output)
        except ProjectionError as e:
            results.append({"candidate_id": candidate_id, "error": str(e)})
            run_errors.append(f"{candidate_id}: {e}")
        except Exception as e:  # noqa: BLE001 - one bad candidate must never kill the batch
            results.append({"candidate_id": candidate_id, "error": f"{type(e).__name__}: {e}"})
            run_errors.append(f"{candidate_id}: unexpected error: {e}")

    return {"results": results, "run_errors": run_errors}
