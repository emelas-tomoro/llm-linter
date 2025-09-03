from __future__ import annotations as _annotations

import ast
import hashlib
import json
import os
import re
from pathlib import Path
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pydantic import BaseModel

from agents import RunContextWrapper, function_tool


class LinterContext(BaseModel):
    repo_path: str
    rules_text: Optional[str] = None
    # Optional scoping and performance controls
    target_subpath: Optional[str] = None
    exclude_dirs: Optional[List[str]] = None
    max_issues_per_tool: Optional[int] = None
    duplication_max_issues: Optional[int] = None
    include_index_sample: bool = False
    index_sample_limit: int = 200


class LinterInput(BaseModel):
    repo_path: str
    target_subpath: Optional[str] = None
    rules_path: Optional[str] = None
    prompt_overrides: Optional[str] = None
    exclude_dirs: Optional[List[str]] = None
    max_issues_per_tool: Optional[int] = None
    duplication_max_issues: Optional[int] = None
    include_index_sample: Optional[bool] = None
    index_sample_limit: Optional[int] = None


class LintIssue(BaseModel):
    rule: str
    path: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    severity: str = "warning"
    message: str
    recommendation: Optional[str] = None
    code_suggestion: Optional[str] = None


class LintReport(BaseModel):
    summary: Dict[str, Any]
    issues: List[LintIssue]


def _normalize_repo_path(context: RunContextWrapper[LinterContext]) -> str:
    base = Path(context.context.repo_path).resolve()
    sub = (context.context.target_subpath or "").strip() if hasattr(context.context, 'target_subpath') else ""
    if sub:
        base = (base / sub).resolve()
    return str(base)


def _iter_files(base_dir: str, include_exts: Tuple[str, ...], exclude_dirs: Optional[set[str]] = None) -> Iterable[str]:
    # Expanded default excludes to avoid scanning dependencies and virtual envs
    exclude_dirs = exclude_dirs or {
        ".git",
        "node_modules",
        "dist",
        "build",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "site-packages",
        "lib",
        "bin",
        "include",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
    for root, _, files in os.walk(base_dir):
        if any(part in exclude_dirs for part in Path(root).parts):
            continue
        for f in files:
            if f.startswith("."):
                continue
            if f.endswith(include_exts):
                yield os.path.join(root, f)


def _read_file_safe(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except Exception:
        return ""


@function_tool(
    name_override="read_code_snippet",
    description_override="Read a small code snippet from a file with optional line range and surrounding context. Returns clipped text.",
)
async def read_code_snippet(
    context: RunContextWrapper[LinterContext],
    path: str,
    line_start: Optional[int] = None,
    line_end: Optional[int] = None,
    context_lines: int = 6,
    max_chars: int = 4000,
) -> str:
    """Safely read a snippet of a file within the repo. Clamps size to avoid huge payloads."""
    logger = logging.getLogger("linter.tools")
    repo_root = Path(_normalize_repo_path(context))
    abs_path = (repo_root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    try:
        abs_path.relative_to(repo_root)
    except Exception:
        return "[read_code_snippet] Error: path is outside repository root"
    text = _read_file_safe(str(abs_path))
    if not text:
        return ""
    lines = text.splitlines()
    n = len(lines)
    if line_start is None and line_end is None:
        # Return head snippet
        snippet = "\n".join(lines[: min(200, n)])
    else:
        s = max(1, line_start or 1)
        e = min(n, line_end or s)
        s_ctx = max(1, s - context_lines)
        e_ctx = min(n, e + context_lines)
        snippet = "\n".join(lines[s_ctx - 1 : e_ctx])
    if len(snippet) > max_chars:
        snippet = snippet[: max_chars] + "\n[clipped]"
    logger.debug("Read snippet from %s", abs_path)
    header = f"// path: {abs_path}\n"
    return header + snippet


@function_tool(name_override="load_rules_text", description_override="Load and concatenate all .md/.txt files under rules_path.")
async def load_rules_text(context: RunContextWrapper[LinterContext], rules_path: Optional[str]) -> str:
    """Load and cache best-practice text into context.

    Parameters:
    - rules_path: Optional absolute/relative directory containing .md/.txt files.

    Returns:
    - A single concatenated string of all rule texts, or existing context rules if none provided.
    """
    logger = logging.getLogger("linter.tools")
    if not rules_path:
        return context.context.rules_text or ""
    base = Path(rules_path)
    if not base.exists():
        return context.context.rules_text or ""
    blobs: List[str] = []
    for ext in (".md", ".txt"):
        for p in base.rglob(f"*{ext}"):
            blobs.append(_read_file_safe(str(p)))
    joined = "\n\n".join(b for b in blobs if b.strip())
    context.context.rules_text = joined
    logger.debug("Loaded rules text from %s (chars=%d)", rules_path, len(joined))
    return joined


@function_tool(name_override="scan_repo_index", description_override="Index repository files and return counts by type. Optionally return a sampled file list.")
async def scan_repo_index(context: RunContextWrapper[LinterContext], target_subpath: Optional[str] = None, include_files: Optional[bool] = None, max_files: Optional[int] = None) -> str:
    """Index repository to compute file counts by extension with optional sampling.

    Parameters:
    - target_subpath: Optional extra subpath under the repo root to index.
    - include_files: If True, include a small sample of file paths (capped by max_files).
    - max_files: Max number of file paths to sample when include_files is True (default from context).

    Returns:
    - JSON string with keys: summary{root, counts_by_ext, num_files} and optional files_sample metadata.
    """
    logger = logging.getLogger("linter.tools")
    base = Path(_normalize_repo_path(context))
    if target_subpath:
        base = base / target_subpath
    base = base.resolve()
    if include_files is None:
        include_files = bool(getattr(context.context, 'include_index_sample', False))
    if max_files is None:
        max_files = int(getattr(context.context, 'index_sample_limit', 200))
    counts: Dict[str, int] = {}
    files_sample: List[str] = []
    exclude = set(getattr(context.context, 'exclude_dirs', []) or []) | {
        ".git",
        "node_modules",
        "dist",
        "build",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "site-packages",
        "lib",
        "bin",
        "include",
    }
    for root, _, fs in os.walk(base):
        if any(part in exclude for part in Path(root).parts):
            continue
        for f in fs:
            if f.startswith("."):
                continue
            p = Path(root) / f
            if include_files and len(files_sample) < max_files:
                files_sample.append(str(p))
            ext = p.suffix or "noext"
            counts[ext] = counts[ext] + 1 if ext in counts else 1
    num_files = sum(counts.values())
    summary = {"root": str(base), "counts_by_ext": counts, "num_files": num_files}
    logger.debug("Indexed repo root=%s files=%d", base, num_files)
    payload: Dict[str, Any] = {"summary": summary}
    if include_files:
        payload["files_sample"] = files_sample
        payload["files_sampled"] = len(files_sample)
        payload["files_sample_limit"] = max_files
    return json.dumps(payload)


@function_tool(name_override="check_complexity_lengths", description_override="Detect long files, classes, and functions in Python and TS/JS.")
async def check_complexity_lengths(context: RunContextWrapper[LinterContext], max_func_lines: int = 50, max_class_lines: int = 400, max_file_lines: int = 1000, max_issues: Optional[int] = None) -> str:
    """Detect long files, classes, and functions using line-count thresholds.

    Parameters:
    - max_func_lines, max_class_lines, max_file_lines: Line thresholds for warnings.
    - max_issues: Cap on number of issues returned (defaults from context).

    Returns:
    - JSON string with summary counts and issues (file_too_long, class_too_long, function_too_long).
    """
    logger = logging.getLogger("linter.tools")
    base = _normalize_repo_path(context)
    issues: List[Dict[str, Any]] = []
    if max_issues is None:
        max_issues = int(getattr(context.context, 'max_issues_per_tool', 300) or 300)
    summary: Dict[str, int] = {"long_files": 0, "long_classes": 0, "long_functions": 0}

    def _add_issue(rule: str, path: str, msg: str, severity: str = "warning", start: Optional[int] = None, end: Optional[int] = None):
        issues.append({"rule": rule, "path": path, "line_start": start, "line_end": end, "severity": severity, "message": msg})

    for f in _iter_files(base, include_exts=(".py", ".ts", ".tsx", ".js", ".jsx")):
        content = _read_file_safe(f)
        line_count = content.count("\n") + 1 if content else 0
        if line_count > max_file_lines:
            summary["long_files"] += 1
            _add_issue("file_too_long", f, f"File has {line_count} lines (>{max_file_lines}). Consider splitting.")

    for f in _iter_files(base, include_exts=(".py",)):
        src = _read_file_safe(f)
        if not src:
            continue
        try:
            tree = ast.parse(src)
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                start = getattr(node, "lineno", None)
                end = getattr(node, "end_lineno", None)
                if start and end and (end - start + 1) > max_class_lines:
                    summary["long_classes"] += 1
                    _add_issue("class_too_long", f, f"Class '{node.name}' is {(end - start + 1)} lines (>{max_class_lines}).", start, end)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = getattr(node, "lineno", None)
                end = getattr(node, "end_lineno", None)
                if start and end and (end - start + 1) > max_func_lines:
                    summary["long_functions"] += 1
                    _add_issue("function_too_long", f, f"Function '{node.name}' is {(end - start + 1)} lines (>{max_func_lines}).", start, end)

    if len(issues) > max_issues:
        issues = issues[:max_issues]
        summary["truncated"] = True
    payload = json.dumps({"summary": summary, "issues": issues})
    logger.debug("Complexity summary: %s", summary)
    return payload


@function_tool(name_override="check_typing_and_docs", description_override="Check Python type hints, docstrings, and comment density.")
async def check_typing_and_docs(context: RunContextWrapper[LinterContext], max_issues: Optional[int] = None) -> str:
    """Analyze Python typing, docstrings, and comment density via AST.

    Flags missing module/class/function docstrings, missing type hints, and low comment density in long files.

    Parameters:
    - max_issues: Cap on number of issues returned (defaults from context).

    Returns:
    - JSON string with summary totals and issues per finding.
    """
    logger = logging.getLogger("linter.tools")
    base = _normalize_repo_path(context)
    issues: List[Dict[str, Any]] = []
    if max_issues is None:
        max_issues = int(getattr(context.context, 'max_issues_per_tool', 300) or 300)
    summary = {"total_functions": 0, "typed_functions": 0, "functions_without_doc": 0, "classes_without_doc": 0}

    def _add(rule: str, path: str, message: str, start: Optional[int] = None):
        issues.append({"rule": rule, "path": path, "line_start": start, "message": message, "severity": "warning"})

    for f in _iter_files(base, include_exts=(".py",)):
        src = _read_file_safe(f)
        if not src:
            continue
        try:
            tree = ast.parse(src)
        except Exception:
            continue
        if ast.get_docstring(tree) in (None, ""):
            _add("missing_module_docstring", f, "Module is missing a top-level docstring.", 1)

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                if ast.get_docstring(node) in (None, ""):
                    _add("missing_class_docstring", f, f"Class '{node.name}' is missing a docstring.", getattr(node, "lineno", None))
                for fn in [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                    summary["total_functions"] += 1
                    has_types = ((fn.returns is not None) and all(arg.annotation is not None for arg in fn.args.args))
                    if has_types:
                        summary["typed_functions"] += 1
                    else:
                        _add("missing_type_hints", f, f"Method '{fn.name}' is missing type hints.", getattr(fn, "lineno", None))
                    if ast.get_docstring(fn) in (None, ""):
                        summary["functions_without_doc"] += 1
                        _add("missing_function_docstring", f, f"Method '{fn.name}' is missing a docstring.", getattr(fn, "lineno", None))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                summary["total_functions"] += 1
                has_types = ((node.returns is not None) and all(arg.annotation is not None for arg in node.args.args))
                if has_types:
                    summary["typed_functions"] += 1
                else:
                    _add("missing_type_hints", f, f"Function '{node.name}' is missing type hints.", getattr(node, "lineno", None))
                if ast.get_docstring(node) in (None, ""):
                    summary["functions_without_doc"] += 1
                    _add("missing_function_docstring", f, f"Function '{node.name}' is missing a docstring.", getattr(node, "lineno", None))

        total_lines = src.count("\n") + 1
        comment_lines = sum(1 for line in src.splitlines() if line.strip().startswith("#"))
        if total_lines >= 50:
            density = comment_lines / max(total_lines, 1)
            if density < 0.02:
                issues.append({"rule": "low_comment_density", "path": f, "message": f"Low comment density ({density:.1%}).", "severity": "info"})

    if len(issues) > max_issues:
        issues = issues[:max_issues]
        summary["truncated"] = True
    payload = json.dumps({"summary": summary, "issues": issues})
    logger.debug("Typing/docs summary: %s", summary)
    return payload


@function_tool(name_override="check_error_handling", description_override="Check presence and quality of try/except blocks and bad patterns.")
async def check_error_handling(context: RunContextWrapper[LinterContext], max_issues: Optional[int] = None) -> str:
    """Assess Python try/except usage for bare or overly broad exception handling.

    Parameters:
    - max_issues: Cap on number of issues returned (defaults from context).

    Returns:
    - JSON string with counts for try/except/bare/broad and corresponding issues.
    """
    logger = logging.getLogger("linter.tools")
    base = _normalize_repo_path(context)
    issues: List[Dict[str, Any]] = []
    if max_issues is None:
        max_issues = int(getattr(context.context, 'max_issues_per_tool', 300) or 300)
    summary = {"try_blocks": 0, "except_blocks": 0, "bare_except": 0, "broad_except": 0}

    def _bad(rule: str, path: str, msg: str, start: Optional[int] = None):
        issues.append({"rule": rule, "path": path, "message": msg, "line_start": start, "severity": "warning"})

    for f in _iter_files(base, include_exts=(".py",)):
        src = _read_file_safe(f)
        if not src:
            continue
        try:
            tree = ast.parse(src)
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                summary["try_blocks"] += 1
                summary["except_blocks"] += len(node.handlers)
                for h in node.handlers:
                    if h.type is None:
                        summary["bare_except"] += 1
                        _bad("bare_except", f, "Bare except detected; catch specific exceptions.", getattr(h, "lineno", None))
                    else:
                        if isinstance(h.type, ast.Name) and h.type.id in {"Exception", "BaseException"}:
                            summary["broad_except"] += 1
                            _bad("broad_except", f, f"Catching broad exception '{h.type.id}'. Prefer specific exception types.", getattr(h, "lineno", None))
    if len(issues) > max_issues:
        issues = issues[:max_issues]
        summary["truncated"] = True
    payload = json.dumps({"summary": summary, "issues": issues})
    logger.debug("Error handling summary: %s", summary)
    return payload


@function_tool(name_override="check_code_duplication", description_override="Detect duplicated 5-line shingles across files (language-agnostic heuristic).")
async def check_code_duplication(context: RunContextWrapper[LinterContext], min_shingle_lines: int = 5, min_occurrences: int = 2, max_issues: Optional[int] = None) -> str:
    """Find near-exact duplicated code blocks using line shingling across files.

    Parameters:
    - min_shingle_lines: Block size (in normalized lines) to consider a duplicate unit.
    - min_occurrences: Minimum occurrences to flag (default 2).
    - max_issues: Cap on number of issues returned (defaults from context).

    Returns:
    - JSON string with duplicated_blocks count and per-location issues.
    """
    logger = logging.getLogger("linter.tools")
    base = _normalize_repo_path(context)
    shingle_map: Dict[str, List[tuple[str, int]]] = {}
    issues: List[Dict[str, Any]] = []
    if max_issues is None:
        max_issues = int(getattr(context.context, 'duplication_max_issues', None) or getattr(context.context, 'max_issues_per_tool', 200) or 200)
    allowed_exts = (".py", ".ts", ".tsx", ".js", ".jsx")

    def normalize_line(line: str) -> str:
        return re.sub(r"\s+", " ", line.strip())

    for f in _iter_files(base, include_exts=allowed_exts):
        lines = [normalize_line(l) for l in _read_file_safe(f).splitlines()]
        if len(lines) < min_shingle_lines:
            continue
        for i in range(0, len(lines) - min_shingle_lines + 1):
            block = "\n".join(lines[i : i + min_shingle_lines])
            if not block.strip():
                continue
            key = hashlib.md5(block.encode("utf-8")).hexdigest()
            shingle_map.setdefault(key, []).append((f, i + 1))

    for key, locs in shingle_map.items():
        if len(locs) >= min_occurrences:
            first = locs[0]
            for path, line in locs[1:]:
                issues.append({"rule": "duplicated_code_block", "path": path, "line_start": line, "message": f"Duplicated {min_shingle_lines}-line block also found in {first[0]}:{first[1]}", "severity": "warning"})
                if len(issues) >= max_issues:
                    break
            if len(issues) >= max_issues:
                break

    if len(issues) > max_issues:
        issues = issues[:max_issues]
        truncated = True
    else:
        truncated = False
    summary = {"duplicated_blocks": len(issues), "truncated": truncated}
    payload = json.dumps({"summary": summary, "issues": issues})
    logger.debug("Duplication summary: %s", summary)
    return payload


@function_tool(name_override="check_class_cohesion", description_override="Heuristic for whether methods belong in their class (usage of self/attributes).")
async def check_class_cohesion(context: RunContextWrapper[LinterContext], max_issues: Optional[int] = None) -> str:
    """Evaluate class cohesion by flagging methods that do not access instance state.

    Parameters:
    - max_issues: Cap on number of issues returned (defaults from context).

    Returns:
    - JSON string with methods_no_self_usage count and related issues.
    """
    logger = logging.getLogger("linter.tools")
    base = _normalize_repo_path(context)
    issues: List[Dict[str, Any]] = []
    if max_issues is None:
        max_issues = int(getattr(context.context, 'max_issues_per_tool', 300) or 300)
    summary: Dict[str, int] = {"methods_no_self_usage": 0}

    for f in _iter_files(base, include_exts=(".py",)):
        src = _read_file_safe(f)
        if not src:
            continue
        try:
            tree = ast.parse(src)
        except Exception:
            continue
        for node in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            for fn in [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                if fn.name.startswith("__") and fn.name.endswith("__"):
                    continue
                has_decorator = any(((getattr(d, "id", None) in {"staticmethod", "classmethod"}) or getattr(d, "attr", None) in {"staticmethod", "classmethod"}) for d in getattr(fn, "decorator_list", []))
                if has_decorator:
                    continue
                uses_self = False
                for n in ast.walk(fn):
                    if getattr(n, "attr", None) and getattr(getattr(n, "value", None), "id", None) == "self":
                        uses_self = True
                        break
                if not uses_self:
                    summary["methods_no_self_usage"] += 1
                    issues.append({"rule": "low_class_cohesion", "path": f, "line_start": getattr(fn, "lineno", None), "message": f"Method '{fn.name}' in class '{node.name}' does not access instance state; consider @staticmethod or moving it.", "severity": "info"})
    if len(issues) > max_issues:
        issues = issues[:max_issues]
        summary["truncated"] = True
    payload = json.dumps({"summary": summary, "issues": issues})
    logger.debug("Class cohesion summary: %s", summary)
    return payload


@function_tool(name_override="check_file_structure", description_override="Assess basic file/directory structure heuristics.")
async def check_file_structure(context: RunContextWrapper[LinterContext], max_issues: Optional[int] = None) -> str:
    """Check directory/file organization heuristics.

    Flags very large directories and Python package directories missing __init__.py.

    Parameters:
    - max_issues: Cap on number of issues returned (defaults from context).

    Returns:
    - JSON string with large_dirs summary and issues list.
    """
    logger = logging.getLogger("linter.tools")
    base = Path(_normalize_repo_path(context))
    issues: List[Dict[str, Any]] = []
    if max_issues is None:
        max_issues = int(getattr(context.context, 'max_issues_per_tool', 300) or 300)
    summary: Dict[str, Any] = {"large_dirs": []}

    for root, dirs, files in os.walk(base):
        if any(part in {".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv", "env", "site-packages", "lib", "bin", "include"} for part in Path(root).parts):
            continue
        if len(files) > 50 and Path(root) != base:
            summary["large_dirs"].append({"path": root, "num_files": len(files)})
            issues.append({"rule": "large_directory", "path": root, "message": f"Directory contains {len(files)} files. Consider sub-structuring to improve navigability.", "severity": "info"})

    for d in [p for p in base.rglob("*") if p.is_dir()]:
        py_files = list(d.glob("*.py"))
        if py_files and not (d / "__init__.py").exists():
            issues.append({"rule": "missing_init_py", "path": str(d), "message": "Python package directory missing __init__.py.", "severity": "warning"})

    if len(issues) > max_issues:
        issues = issues[:max_issues]
        summary["truncated"] = True
    payload = json.dumps({"summary": summary, "issues": issues})
    logger.debug("File structure issues=%d", len(issues))
    return payload


@function_tool(name_override="check_tests", description_override="Estimate test coverage by file counts and presence of test directories (Python and JS/TS).")
async def check_tests(context: RunContextWrapper[LinterContext], max_issues: Optional[int] = None) -> str:
    """Estimate test coverage by comparing test file counts to implementation files by language.

    Parameters:
    - max_issues: Cap on number of issues returned (defaults from context).

    Returns:
    - JSON string with per-language file counts/ratios and low-coverage issues.
    """
    logger = logging.getLogger("linter.tools")
    base = Path(_normalize_repo_path(context))
    impl_py = len(list(_iter_files(str(base), include_exts=(".py",))))
    impl_ts = len(list(_iter_files(str(base), include_exts=(".ts", ".tsx"))))
    impl_js = len(list(_iter_files(str(base), include_exts=(".js", ".jsx"))))

    test_py = sum(1 for p in _iter_files(str(base), include_exts=(".py",)) if re.search(r"(^|/)tests?/|(^|/)test_", p))
    test_ts = sum(1 for p in _iter_files(str(base), include_exts=(".ts", ".tsx")) if re.search(r"\.test\.|/__tests__/,?", p))
    test_js = sum(1 for p in _iter_files(str(base), include_exts=(".js", ".jsx")) if re.search(r"\.test\.|/__tests__/,?", p))

    def pct(n: int, d: int) -> float:
        return (n / d * 100.0) if d else 0.0

    summary = {
        "python_impl_files": impl_py,
        "python_test_files": test_py,
        "python_test_file_ratio_pct": round(pct(test_py, impl_py), 1),
        "ts_impl_files": impl_ts,
        "ts_test_files": test_ts,
        "ts_test_file_ratio_pct": round(pct(test_ts, impl_ts), 1),
        "js_impl_files": impl_js,
        "js_test_files": test_js,
        "js_test_file_ratio_pct": round(pct(test_js, impl_js), 1),
    }

    issues: List[Dict[str, Any]] = []
    if max_issues is None:
        max_issues = int(getattr(context.context, 'max_issues_per_tool', 300) or 300)
    if impl_py and summary["python_test_file_ratio_pct"] < 10.0:
        issues.append({"rule": "low_test_coverage_python", "path": str(base), "message": f"Low Python test file ratio (~{summary['python_test_file_ratio_pct']}%). Consider adding tests.", "severity": "warning"})
    if impl_ts and summary["ts_test_file_ratio_pct"] < 10.0:
        issues.append({"rule": "low_test_coverage_ts", "path": str(base), "message": f"Low TS test file ratio (~{summary['ts_test_file_ratio_pct']}%). Consider adding tests.", "severity": "warning"})
    if impl_js and summary["js_test_file_ratio_pct"] < 10.0:
        issues.append({"rule": "low_test_coverage_js", "path": str(base), "message": f"Low JS test file ratio (~{summary['js_test_file_ratio_pct']}%). Consider adding tests.", "severity": "warning"})
    if len(issues) > max_issues:
        issues = issues[:max_issues]
        summary["truncated"] = True
    payload = json.dumps({"summary": summary, "issues": issues})
    logger.debug("Testing summary: %s", summary)
    return payload


@function_tool(name_override="check_security_heuristics", description_override="Simple security lint for dangerous calls and leaked secrets.")
async def check_security_heuristics(context: RunContextWrapper[LinterContext], max_issues: Optional[int] = None) -> str:
    """Scan for common security smells via regex (eval/exec, subprocess shell=True, secrets, pickle).

    Parameters:
    - max_issues: Cap on number of issues returned (defaults from context).

    Returns:
    - JSON string with total matches and per-location issues.
    """
    logger = logging.getLogger("linter.tools")
    base = _normalize_repo_path(context)
    issues: List[Dict[str, Any]] = []
    if max_issues is None:
        max_issues = int(getattr(context.context, 'max_issues_per_tool', 300) or 300)
    patterns = [
        (r"\beval\(\)", "use_of_eval"),
        (r"exec\(", "use_of_exec"),
        (r"subprocess\.[a-zA-Z_]+\(.*shell\s*=\s*True", "subprocess_shell_true"),
        (r"aws_secret_access_key|api_key|token\s*=\s*['\"]", "potential_secret_leak"),
        (r"pickle\.(load|loads)", "unsafe_pickle_usage"),
    ]
    for f in _iter_files(base, include_exts=(".py", ".js", ".ts", ".tsx")):
        content = _read_file_safe(f)
        for pat, rule in patterns:
            for m in re.finditer(pat, content):
                issues.append({"rule": rule, "path": f, "line_start": content[: m.start()].count("\n") + 1, "message": f"Suspicious pattern '{rule}' detected.", "severity": "warning"})
    if len(issues) > max_issues:
        issues = issues[:max_issues]
        truncated = True
    else:
        truncated = False
    payload = json.dumps({"summary": {"issues": len(issues), "truncated": truncated}, "issues": issues})
    logger.debug("Security issues=%d", len(issues))
    return payload


def create_linter_context(repo_path: str, rules_path: Optional[str] = None, prompt_overrides: Optional[str] = None) -> LinterContext:
    ctx = LinterContext(repo_path=str(Path(repo_path).resolve()))
    if rules_path and Path(rules_path).exists():
        blobs: List[str] = []
        for ext in (".md", ".txt"):
            for p in Path(rules_path).rglob(f"*{ext}"):
                blobs.append(_read_file_safe(str(p)))
        ctx.rules_text = "\n\n".join(b for b in blobs if b.strip())
    if prompt_overrides:
        ctx.rules_text = ((ctx.rules_text or "") + "\n\n" + prompt_overrides).strip()
    return ctx


