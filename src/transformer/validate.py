"""
Final validation gate: checked AFTER projection, right before the pipeline
hands output back to the caller. This is intentionally a *second*, simpler
pass on top of project()'s own checks -- the point is that nothing leaves
the pipeline without an explicit "this matches what was asked for" check,
rather than trusting the projection step never to regress.
"""

VALID_TYPES = {"string", "number", "boolean", "string[]", "object", "object[]"}


def validate_config(config):
    """Sanity-check a runtime config before we even try to run it."""
    errors = []
    if "fields" not in config or not isinstance(config["fields"], list) or not config["fields"]:
        errors.append("config must have a non-empty 'fields' list")
        return errors
    seen_paths = set()
    for i, spec in enumerate(config["fields"]):
        if "path" not in spec:
            errors.append(f"fields[{i}] is missing 'path'")
            continue
        if spec["path"] in seen_paths:
            errors.append(f"duplicate output field '{spec['path']}'")
        seen_paths.add(spec["path"])
        if "type" in spec and spec["type"] not in VALID_TYPES:
            errors.append(f"fields[{i}] ('{spec['path']}') has unknown type '{spec['type']}'")
    if config.get("on_missing") not in (None, "null", "omit", "error"):
        errors.append(f"on_missing must be one of null/omit/error, got '{config.get('on_missing')}'")
    return errors


def validate_output(output, config):
    """Check the projected output actually matches what the config asked
    for: every non-omitted field present, types roughly right, nothing
    unexpected snuck in."""
    errors = []
    expected_keys = {spec["path"] for spec in config["fields"]}
    if config.get("include_confidence", True):
        expected_keys.add("overall_confidence")
    if config.get("include_provenance", True):
        expected_keys.add("provenance")
        expected_keys.add("source_errors")

    on_missing = config.get("on_missing", "null")
    for spec in config["fields"]:
        key = spec["path"]
        if key not in output:
            if on_missing != "omit":
                errors.append(f"expected field '{key}' is absent from output")
            continue
        value = output[key]
        type_ = spec.get("type")
        if value is None:
            continue  # null is a valid, explicit "we don't know"
        if type_ == "string[]" and not isinstance(value, list):
            errors.append(f"field '{key}' should be a list, got {type(value).__name__}")
        if type_ == "number" and not isinstance(value, (int, float)):
            errors.append(f"field '{key}' should be a number, got {type(value).__name__}")
        if type_ == "string" and not isinstance(value, str):
            errors.append(f"field '{key}' should be a string, got {type(value).__name__}")

    unexpected = set(output.keys()) - expected_keys
    if unexpected:
        errors.append(f"unexpected keys in output not requested by config: {sorted(unexpected)}")

    return errors
