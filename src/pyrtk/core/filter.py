# src/pyrtk/core/filter.py
from __future__ import annotations

import json
import os
import re
from enum import Enum

_DEDUP_SYMBOL = os.getenv("RTK_DEDUP_SYMBOL", "×")
_BLANK_LINES_RE = re.compile(r'\n{3,}')
_C_BLOCK_COMMENT_RE = re.compile(r'/\*.*?\*/', re.DOTALL)


class FilterLevel(Enum):
    NONE = "none"
    MINIMAL = "minimal"        # strip comments + collapse blanks (~20-40%)
    AGGRESSIVE = "aggressive"  # strip function bodies, keep signatures (~60-90%)


_LANGUAGE_LINE_COMMENT: dict[str, str] = {
    "python": "#", "ruby": "#",
    "javascript": "//", "typescript": "//",
    "go": "//", "rust": "//", "java": "//",
    "csharp": "//", "c": "//", "kotlin": "//",
}


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
                result.append(f"{current_line} ({_DEDUP_SYMBOL}{count})")
            else:
                result.append(current_line)
            current_line = line
            count = 1
    if count > 1:
        result.append(f"{current_line} ({_DEDUP_SYMBOL}{count})")
    else:
        result.append(current_line)
    return "\n".join(result)


def structure_only(json_str: str) -> str:
    """Parses JSON, replaces primitive values with type names, preserves keys."""
    try:
        data = json.loads(json_str)

        def convert(val, depth: int = 0):
            if depth > 10:
                return "..."
            if val is None:
                return "null"
            if isinstance(val, dict):
                return {k: convert(v, depth + 1) for k, v in val.items()}
            elif isinstance(val, list):
                return [convert(val[0], depth + 1)] if val else []
            else:
                return type(val).__name__

        return json.dumps(convert(data), indent=2)
    except json.JSONDecodeError:
        return json_str


def code_filter(content: str, language: str, level: FilterLevel = FilterLevel.MINIMAL) -> str:
    """Language-aware source code compression.

    Args:
        content:  Raw file text.
        language: Language key from LANGUAGE_MAP in read_cmd.py.
        level:    Compression level.

    Returns:
        Compressed text, or original if language is unsupported.
    """
    if level == FilterLevel.NONE or language == "unknown":
        return content
    if level == FilterLevel.MINIMAL:
        return _minimal_filter(content, language)
    if level == FilterLevel.AGGRESSIVE:
        return _aggressive_filter(content, language)
    return content


def _minimal_filter(content: str, language: str) -> str:
    """Strip comments and collapse 3+ blank lines into one.

    NOTE: This is line-based comment/brace stripping and is not fully string-literal-aware.
    Lines starting with comment markers inside multi-line strings or template literals
    might be stripped.
    """
    line_prefix = _LANGUAGE_LINE_COMMENT.get(language)
    if not line_prefix:
        return content

    # Strip C-style block comments for C-family languages
    if language not in ("python", "ruby"):
        content = _C_BLOCK_COMMENT_RE.sub("", content)
    elif language == "ruby":
        content = re.sub(r"^=begin.*?^=end", "", content, flags=re.MULTILINE | re.DOTALL)

    result = []
    in_triple_quote = False
    for line in content.splitlines():
        stripped = line.strip()
        
        # Avoid stripping comments inside Python multi-line triple-quoted strings
        if language == "python" and stripped:
            if stripped.count('"""') % 2 == 1 or stripped.count("'''") % 2 == 1:
                in_triple_quote = not in_triple_quote

        if not in_triple_quote and stripped.startswith(line_prefix):
            continue
        result.append(line)

    joined = "\n".join(result)
    return _BLANK_LINES_RE.sub("\n\n", joined).strip()


def _aggressive_filter(content: str, language: str) -> str:
    """Minimal-filter first, then strip function bodies."""
    content = _minimal_filter(content, language)
    if language == "python":
        return _aggressive_python(content)
    if language in ("javascript", "typescript", "go", "rust", "java", "csharp", "c", "kotlin"):
        return _aggressive_brace(content)
    return content  # unsupported — return minimal-filtered


def _aggressive_python(content: str) -> str:
    """Python: keep imports, decorators, class/def signatures + docstrings. Drop bodies."""
    lines = content.splitlines()
    result: list[str] = []
    skip_until_indent: int | None = None
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        indent = len(line) - len(line.lstrip()) if stripped else 999

        # Resume from skip when we dedent back to signature level
        if skip_until_indent is not None:
            if stripped and indent <= skip_until_indent:
                skip_until_indent = None
            else:
                i += 1
                continue

        is_sig = stripped.startswith(("def ", "async def ", "class "))
        is_keep = (
            not stripped
            or stripped.startswith(("import ", "from ", "@", "__all__", "__version__", "__slots__"))
            or is_sig
        )

        if is_keep:
            result.append(line)

            if is_sig:
                # Look ahead for docstring
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and lines[j].strip().startswith(('"""', "'''")):
                    quote = lines[j].strip()[:3]
                    result.append(lines[j])
                    if lines[j].count(quote) < 2:  # multi-line docstring
                        j += 1
                        while j < len(lines):
                            result.append(lines[j])
                            if quote in lines[j].strip():
                                    j += 1
                                    break
                            j += 1
                    else:
                        j += 1
                    i = j

                # Add ellipsis body placeholder and start skipping
                sig_indent = indent
                body_indent = " " * (sig_indent + 4)
                result.append(f"{body_indent}...")
                skip_until_indent = sig_indent
                i += 1
                continue

        elif indent == 0 and stripped and "=" in stripped:
            # Keep module-level assignments (constants, __all__, etc.)
            result.append(line)

        i += 1

    return "\n".join(result)


def _aggressive_brace(content: str) -> str:
    """Brace-delimited languages: keep signatures, replace bodies with { ... }.

    NOTE: This is line-based brace depth tracking and is not string-literal-aware.
    Curly braces '{' or '}' appearing inside string literals or comments will throw
    off depth tracking.
    """
    _SIG_RE = re.compile(
        r"\b(public|private|protected|internal|static|async|"
        r"func|fn|fun|void|int|string|bool|"
        r"class|struct|interface|impl|enum|type)\b"
    )

    lines = content.splitlines()
    result: list[str] = []
    brace_depth = 0
    body_start_depth: int | None = None

    for line in lines:
        stripped = line.strip()
        open_b = line.count("{")
        close_b = line.count("}")
        is_sig = bool(_SIG_RE.search(stripped))
        is_structural = stripped.startswith(("import ", "using ", "package ", "#include", "//"))

        if body_start_depth is None:
            result.append(line)
            if (is_sig or is_structural) and open_b > close_b:
                body_start_depth = brace_depth
                result.append("  ...")
            brace_depth += open_b - close_b
        else:
            brace_depth += open_b - close_b
            if brace_depth <= body_start_depth:
                result.append(line)
                body_start_depth = None

    return "\n".join(result)
