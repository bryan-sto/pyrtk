# src/pyrtk/core/filter.py
from __future__ import annotations

import ast
import json
import os
import re
from enum import Enum

_DEDUP_SYMBOL = os.getenv("RTK_DEDUP_SYMBOL", "×")
_BLANK_LINES_RE = re.compile(r'\n{3,}')
_C_TOKEN_RE = re.compile(
    r"""
      "(?:\\.|[^"\\\n])*"
    | '(?:\\.|[^'\\\n])*'
    | `(?:\\.|[^`\\])*`
    | //[^\n]*
    | /\*[\s\S]*?\*/
    """,
    re.VERBOSE,
)


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


def _strip_c_block_comments(content: str) -> str:
    """Strip C-style /* ... */ block comments while leaving strings and line comments intact."""
    def _repl(match: re.Match[str]) -> str:
        text = match.group(0)
        return "" if text.startswith("/*") else text

    return _C_TOKEN_RE.sub(_repl, content)


def _minimal_filter(content: str, language: str) -> str:
    """Strip comments and collapse 3+ blank lines into one.

    NOTE: This is line-based comment/brace stripping and is not fully string-literal-aware.
    Lines starting with comment markers inside multi-line strings or template literals
    might be stripped.
    """
    line_prefix = _LANGUAGE_LINE_COMMENT.get(language)
    if not line_prefix:
        return content

    # Strip C-style block comments for C-family languages without touching string literals
    if language not in ("python", "ruby"):
        content = _strip_c_block_comments(content)
    elif language == "ruby":
        content = re.sub(r"^=begin.*?^=end", "", content, flags=re.MULTILINE | re.DOTALL)

    result = []
    in_triple_quote = False
    in_backtick = False
    for line in content.splitlines():
        stripped = line.strip()

        # Avoid stripping comments inside Python multi-line triple-quoted strings
        if language == "python" and stripped:
            if stripped.count('"""') % 2 == 1 or stripped.count("'''") % 2 == 1:
                in_triple_quote = not in_triple_quote

        # Avoid stripping comments inside JS/TS/Go backtick multi-line strings / template literals
        if language in ("javascript", "typescript", "go") and stripped:
            backtick_count = len(re.findall(r'(?<!\\)`', stripped))
            if backtick_count % 2 == 1:
                in_backtick = not in_backtick

        if not in_triple_quote and not in_backtick and stripped.startswith(line_prefix):
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


def _is_docstring_stmt(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _slice_header_lines(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    lines: list[str],
) -> tuple[list[str], str]:
    """Return (decorator_and_header_lines, body_indent) for a def/class AST node."""
    out: list[str] = []
    for dec in node.decorator_list:
        dec_end = dec.end_lineno or dec.lineno
        out.extend(lines[dec.lineno - 1 : dec_end])

    first_stmt = node.body[0]
    if first_stmt.lineno == node.lineno:
        header_line = lines[node.lineno - 1][: first_stmt.col_offset].rstrip()
        out.append(header_line)
        body_indent = " " * (node.col_offset + 4)
    else:
        header_lines = lines[node.lineno - 1 : first_stmt.lineno - 1]
        while header_lines and not header_lines[-1].strip():
            header_lines.pop()
        out.extend(header_lines)
        indent_count = first_stmt.col_offset if first_stmt.col_offset > node.col_offset else node.col_offset + 4
        body_indent = " " * indent_count
    return out, body_indent


def _format_docstring(stmt: ast.stmt, node_lineno: int, body_indent: str, lines: list[str]) -> list[str]:
    if stmt.lineno == node_lineno:
        end_col = stmt.end_col_offset if stmt.end_col_offset is not None else len(lines[stmt.lineno - 1])
        seg = lines[stmt.lineno - 1][stmt.col_offset : end_col]
        return [f"{body_indent}{seg}"]
    end_line = stmt.end_lineno or stmt.lineno
    return lines[stmt.lineno - 1 : end_line]


def _format_func_stub(node: ast.FunctionDef | ast.AsyncFunctionDef, lines: list[str]) -> list[str]:
    out, body_indent = _slice_header_lines(node, lines)
    first_stmt = node.body[0]
    if _is_docstring_stmt(first_stmt):
        out.extend(_format_docstring(first_stmt, node.lineno, body_indent, lines))
    out.append(f"{body_indent}...")
    return out


def _format_class_stub(node: ast.ClassDef, lines: list[str]) -> list[str]:
    out, body_indent = _slice_header_lines(node, lines)
    body_stmts = node.body
    if body_stmts and _is_docstring_stmt(body_stmts[0]):
        out.extend(_format_docstring(body_stmts[0], node.lineno, body_indent, lines))
        body_stmts = body_stmts[1:]

    kept_member = False
    for stmt in body_stmts:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.extend(_format_func_stub(stmt, lines))
            kept_member = True
        elif isinstance(stmt, ast.ClassDef):
            out.extend(_format_class_stub(stmt, lines))
            kept_member = True
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            end_line = stmt.end_lineno or stmt.lineno
            out.extend(lines[stmt.lineno - 1 : end_line])
            kept_member = True

    if not kept_member:
        out.append(f"{body_indent}...")
    return out


def _aggressive_python_fallback(content: str) -> str:
    """Line-based fallback when Python source cannot be parsed by ast.parse."""
    lines = content.splitlines()
    result: list[str] = []
    skip_until_indent: int | None = None
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        indent = len(line) - len(line.lstrip()) if stripped else 999

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
            if is_sig:
                sig_indent = indent
                while i < len(lines):
                    sig_line = lines[i]
                    result.append(sig_line)
                    stripped_sig = sig_line.strip()
                    cleaned = re.sub(r"#.*$", "", stripped_sig).rstrip()
                    if cleaned.endswith(":"):
                        break
                    i += 1

                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and lines[j].strip().startswith(('"""', "'''")):
                    quote = lines[j].strip()[:3]
                    result.append(lines[j])
                    if lines[j].count(quote) < 2:
                        j += 1
                        while j < len(lines):
                            result.append(lines[j])
                            if quote in lines[j].strip():
                                j += 1
                                break
                            j += 1
                    else:
                        j += 1
                    i = j - 1

                body_indent = " " * (sig_indent + 4)
                result.append(f"{body_indent}...")
                skip_until_indent = sig_indent
                i += 1
                continue
            else:
                result.append(line)

        elif indent == 0 and stripped and "=" in stripped:
            result.append(line)

        i += 1

    return "\n".join(result)


def _aggressive_python(content: str) -> str:
    """Python: keep imports, assignments, decorators, class/def signatures + docstrings. Drop bodies."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return _aggressive_python_fallback(content)

    lines = content.splitlines()
    result: list[str] = []

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign, ast.AugAssign)):
            end_line = node.end_lineno or node.lineno
            result.extend(lines[node.lineno - 1 : end_line])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if result and result[-1] != "":
                result.append("")
            result.extend(_format_func_stub(node, lines))
        elif isinstance(node, ast.ClassDef):
            if result and result[-1] != "":
                result.append("")
            result.extend(_format_class_stub(node, lines))

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
    pending_sig = False

    for line in lines:
        stripped = line.strip()
        open_b = line.count("{")
        close_b = line.count("}")
        is_sig = bool(_SIG_RE.search(stripped))
        is_structural = stripped.startswith(("import ", "using ", "package ", "#include", "//"))

        if body_start_depth is None:
            result.append(line)
            should_open_body = (is_sig or is_structural or pending_sig) and open_b > close_b
            if should_open_body:
                body_start_depth = brace_depth
                result.append("  ...")
                pending_sig = False
            elif is_sig and open_b == 0:
                pending_sig = True
            elif stripped and not is_sig and not is_structural and open_b == 0:
                pending_sig = False

            brace_depth += open_b - close_b
        else:
            brace_depth += open_b - close_b
            if brace_depth <= body_start_depth:
                result.append(line)
                body_start_depth = None

    return "\n".join(result)
