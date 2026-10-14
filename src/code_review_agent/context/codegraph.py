"""Lightweight code graph: what surrounds the functions a pull request changed.

The diff shows what changed, not how the changed code is used. For every changed Python function this module
finds, by plain `ast` parsing (no vector database, no language server):

  - its callees: repository functions it calls,
  - its callers: repository functions that call it,
  - its tests: test functions that mention it,
  - its class: the `__init__` of the class a changed method belongs to,

and returns them as short snippets plus a few plain facts ("no test function mentions `escalate_stale`").
Calls are matched BY NAME (`obj.save()` matches any function called `save`): fast and good enough for review, but
it can match the wrong function, so the model is told so and names defined many times are not followed.

Pure functions: files in, snippets out. Nothing here reads the disk or the network.
"""

from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from ..schemas import RelatedSnippet

MAX_SYMBOLS = 8  # changed functions we look around (the ones with most added lines first)
MAX_PER_KIND = 3  # callers, callees and tests kept per changed function
MAX_SNIPPET_LINES = 60
MAX_TOTAL_CHARS = 15_000
AMBIGUOUS_NAME_LIMIT = 4  # a name defined this many times or more is too generic to follow (`get`, `save`...)
_BUILTINS = set(dir(builtins))


@dataclass
class _Function:
    path: str
    qualname: str
    name: str
    start: int  # first line, including decorators
    end: int
    node: ast.AST = field(repr=False)
    is_test: bool
    owner: str | None = None  # qualified name of the class this is a method of


def is_test_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    name = parts[-1] if parts else ""
    directories = parts[:-1]
    return "tests" in directories or "test" in directories or name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def _functions(path: str, tree: ast.AST) -> list[_Function]:
    found: list[_Function] = []
    test_file = is_test_path(path)

    def visit(node: ast.AST, prefix: str, owner: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{prefix}{child.name}"
                start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                found.append(_Function(path, qual, child.name, start, child.end_lineno or child.lineno, child,
                                       test_file or child.name.startswith("test_"), owner))
                visit(child, qual + ".", None)
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.", f"{prefix}{child.name}")
            else:
                visit(child, prefix, owner)

    visit(tree, "", None)
    return found


def _called_names(fn: _Function) -> set[str]:
    names = set()
    for node in ast.walk(fn.node):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Attribute):
                names.add(target.attr)
    return names


def _mentioned_names(fn: _Function) -> set[str]:
    names = set()
    for node in ast.walk(fn.node):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _snippet(fn: _Function, files: dict[str, str], kind: str, symbol: str) -> RelatedSnippet:
    lines = files[fn.path].splitlines()
    end = min(fn.end, fn.start + MAX_SNIPPET_LINES - 1)
    text = "\n".join(lines[fn.start - 1:end])
    if end < fn.end:
        text += f"\n# ... ({fn.end - end} more lines not shown)"
    return RelatedSnippet(path=fn.path, start_line=fn.start, end_line=end, kind=kind, symbol=symbol, name=fn.qualname, text=text)


def build_pack(
    added: dict[str, set[int]], files: dict[str, str], max_symbols: int = MAX_SYMBOLS
) -> tuple[list[RelatedSnippet], list[str]]:
    """Related snippets and facts for the functions that the added lines touch.

    `added`: file -> line numbers the pull request adds (new-file numbering). `files`: path -> full Python source at
    the reviewed commit. Files that do not parse are skipped. Returns (snippets, facts).
    """
    index: dict[str, list[_Function]] = {}
    for path, source in files.items():
        try:
            index[path] = _functions(path, ast.parse(source))
        except (SyntaxError, ValueError, RecursionError):
            continue
    every = [fn for fns in index.values() for fn in fns]
    by_name: dict[str, list[_Function]] = {}
    for fn in every:
        by_name.setdefault(fn.name, []).append(fn)

    # The functions this change touches, those with the most added lines first. Tests are not the subject of the
    # search (they are what we look for), but a test the PR adds still counts as a test of the code it exercises.
    changed: list[tuple[int, _Function]] = []
    touched_ids: set[int] = set()  # every function with an added line: already visible in the diff
    for path, lines in added.items():
        for fn in index.get(path, []):
            touched = len([n for n in lines if fn.start <= n <= fn.end])
            if touched:
                touched_ids.add(id(fn))
            inner_changed = any(
                other is not fn and fn.start <= other.start and other.end <= fn.end
                and any(other.start <= n <= other.end for n in lines)
                for other in index[path]
            )
            if touched and not inner_changed and not fn.is_test:  # a container whose inner function changed is not the change
                changed.append((touched, fn))
    changed.sort(key=lambda item: (-item[0], item[1].path, item[1].start))
    changed_fns = [fn for _, fn in changed[:max_symbols]]
    changed_ids = {id(fn) for fn in changed_fns}

    facts: list[str] = []
    per_symbol: list[dict[str, list[_Function]]] = []
    for fn in changed_fns:
        callees: list[_Function] = []
        for name in sorted(_called_names(fn) - _BUILTINS):
            candidates = [c for c in by_name.get(name, []) if c is not fn and not c.is_test and id(c) not in changed_ids]
            if 0 < len(candidates) < AMBIGUOUS_NAME_LIMIT:
                callees += candidates
        # A constructor is called by the name of its class.
        search_name = fn.owner.split(".")[-1] if fn.name == "__init__" and fn.owner else fn.name
        callers: list[_Function] = []  # every caller, including those that are in the diff (they are counted, not repeated)
        tests: list[_Function] = []  # every test that mentions it, including the ones this PR adds
        for other in every:
            if other is fn:
                continue
            if other.is_test:
                if search_name in _mentioned_names(other):
                    tests.append(other)
            elif search_name in _called_names(other):
                callers.append(other)
        klass: list[_Function] = []
        if fn.owner and fn.name != "__init__":
            klass = [c for c in index[fn.path] if c.owner == fn.owner and c.name == "__init__" and id(c) not in changed_ids]
        # Tests already shown in the diff are not repeated as snippets, only counted.
        per_symbol.append({"caller": [c for c in callers if id(c) not in touched_ids],
                           "test": [t for t in tests if id(t) not in touched_ids],
                           "callee": callees, "class": klass})

        added_tests = len([t for t in tests if id(t) in touched_ids])
        mention = "mentioned in no test function."
        if tests:
            mention = f"mentioned in {len(tests)} test function(s)" + (f" ({added_tests} added or changed by this change)." if added_tests else ".")
        facts.append(f"`{fn.qualname}` ({fn.path}) is called by {len(callers)} other repository function(s) and {mention}")

    # Round-robin over kinds and symbols so one busy function cannot use the whole budget.
    snippets: list[RelatedSnippet] = []
    seen: set[tuple[str, int]] = set()
    total = 0
    for rank in range(MAX_PER_KIND):
        for kind in ("caller", "test", "class", "callee"):
            for fn, groups in zip(changed_fns, per_symbol, strict=True):
                group = groups[kind]
                if rank >= len(group):
                    continue
                target = group[rank]
                key = (target.path, target.start)
                if key in seen:
                    continue
                snip = _snippet(target, files, kind, fn.qualname)
                if total + len(snip.text) > MAX_TOTAL_CHARS:
                    facts.append(f"Related code was cut at {MAX_TOTAL_CHARS} characters; some callers, callees or tests are not shown.")
                    return snippets, list(dict.fromkeys(facts))
                seen.add(key)
                total += len(snip.text)
                snippets.append(snip)
    return snippets, list(dict.fromkeys(facts))
