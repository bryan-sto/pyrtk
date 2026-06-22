# src/pyrtk/core/filter.py
import re
import json

def dedup(text: str) -> str:
    """Collapses consecutive repeating log lines and adds count suffix."""
    lines = text.splitlines()
    if not lines:
        return ""
    result = []
    current_line = lines[0]
    count = 1
    for line in lines[1:]:
        if line == current_line:
            count += 1
        else:
            if count > 1:
                result.append(f"{current_line} (×{count})")
            else:
                result.append(current_line)
            current_line = line
            count = 1
    if count > 1:
        result.append(f"{current_line} (×{count})")
    else:
        result.append(current_line)
    return "\n".join(result)

def structure_only(json_str: str) -> str:
    """Parses JSON, replaces primitive values with type names, preserves keys."""
    try:
        data = json.loads(json_str)
        def convert(val):
            if isinstance(val, dict):
                return {k: convert(v) for k, v in val.items()}
            elif isinstance(val, list):
                if not val:
                    return []
                return [convert(val[0])]
            else:
                return type(val).__name__
        return json.dumps(convert(data), indent=2)
    except json.JSONDecodeError:
        return json_str

def dual_mode_parse(raw_output: str, fallback_parser) -> str:
    """Tries parsing raw output as JSON, formats cleanly. Fallback if not valid JSON."""
    try:
        stripped = raw_output.strip()
        if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]")):
            parsed = json.loads(stripped)
            return json.dumps(parsed, separators=(',', ':'))
    except json.JSONDecodeError:
        pass
    return fallback_parser(raw_output)
