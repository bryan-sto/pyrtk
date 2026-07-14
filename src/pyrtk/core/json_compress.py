# src/pyrtk/core/json_compress.py
from __future__ import annotations

import json
from .utils import estimate_tokens

def compress_json(data: any, max_rows: int = 20) -> dict:
    """Compress JSON data by converting arrays of dicts to columnar form and applying CCR truncation."""
    original_str = json.dumps(data)
    orig_tokens = estimate_tokens(original_str)

    # Shape detection
    if isinstance(data, list) and len(data) > 0 and all(isinstance(x, dict) for x in data):
        compressed_data = _compress_columnar(data, max_rows)
    else:
        compressed_data = _truncate_generic(data, max_rows)

    compressed_str = json.dumps(compressed_data, indent=2)
    comp_tokens = estimate_tokens(compressed_str)

    return {
        "compressed": compressed_data,
        "original_tokens_est": orig_tokens,
        "compressed_tokens_est": comp_tokens
    }

def _compress_columnar(rows: list[dict], max_rows: int) -> dict:
    # 1. Identify all keys
    all_keys = []
    for r in rows:
        for k in r.keys():
            if k not in all_keys:
                all_keys.append(k)

    total_rows = len(rows)
    defaults = {}
    schema = []

    # 2. Hoist dominant defaults (>90% frequency)
    for k in all_keys:
        val_counts = {}
        for r in rows:
            val = r.get(k)
            # Use string representation of value for dict keys to handle unhashable types
            try:
                hash(val)
                key_val = val
            except TypeError:
                key_val = json.dumps(val)
            val_counts[key_val] = val_counts.get(key_val, 0) + 1

        if not val_counts:
            continue

        dominant_val = max(val_counts, key=val_counts.get)
        dominant_count = val_counts[dominant_val]

        # Check if dominant value is >=90% of rows
        if dominant_count / total_rows >= 0.9:
            # If dominant_val was serialized, deserialize it
            if isinstance(dominant_val, str) and dominant_val.startswith(("[", "{")):
                try:
                    dominant_val = json.loads(dominant_val)
                except Exception:
                    pass
            defaults[k] = dominant_val
            
            # If not 100% identical, we keep key in schema to show deviations
            if dominant_count < total_rows:
                schema.append(k)
        else:
            schema.append(k)

    # 3. Truncation and CCR caching
    has_truncation = len(rows) > max_rows
    if has_truncation:
        half = max_rows // 2
        keep_first = rows[:half]
        keep_last = rows[-half:]
        omitted = rows[half:-half]

        from ..registry import registry
        ref = registry.ccr_store(omitted, source_tool="json_compress")
        
        target_rows = keep_first + [{"ref": ref, "omitted": len(omitted)}] + keep_last
    else:
        target_rows = rows

    # 4. Generate compressed rows format
    formatted_rows = []
    for r in target_rows:
        if isinstance(r, dict) and "ref" in r and "omitted" in r:
            # Omitted placeholder
            formatted_rows.append(r)
        else:
            row_vals = []
            for k in schema:
                val = r.get(k)
                if k in defaults and val == defaults[k]:
                    # Matches default, show placeholder to save tokens
                    row_vals.append("_")
                else:
                    row_vals.append(val)
            formatted_rows.append(row_vals)

    res = {
        "schema": schema,
        "rows": formatted_rows
    }
    if defaults:
        res["defaults"] = defaults
    return res

def _truncate_generic(data: any, max_rows: int) -> any:
    """Truncate lists or dicts that are not homogeneous arrays of dicts."""
    if isinstance(data, list):
        if len(data) > max_rows:
            half = max_rows // 2
            keep_first = data[:half]
            keep_last = data[-half:]
            omitted = data[half:-half]
            
            from ..registry import registry
            ref = registry.ccr_store(omitted, source_tool="json_compress")
            
            return keep_first + [{"ref": ref, "omitted": len(omitted)}] + keep_last
        else:
            return [_truncate_generic(x, max_rows) for x in data]
    elif isinstance(data, dict):
        return {k: _truncate_generic(v, max_rows) for k, v in data.items()}
    return data
