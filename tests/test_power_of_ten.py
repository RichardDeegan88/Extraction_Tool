"""Power of Ten (NASA/JPL) static-analysis gates.

These tests translate the JPL *Power of Ten* rules for safety-critical code
into mechanical gates for this Python codebase. The canonical constraint list
lives in AGENTS.md (section "JPL Power-of-Ten Constraints" / "Complexity Gates").

Design
------
All checks are pure AST analysis over *production* sources:

    src/extraction_tool/**/*.py
    preprocess_pdf.py
    fetch_readings.py

Test files (``tests/**``) are exempt from structural gates because they are
not shipped. ``__init__.py`` files are exempt from the function-length and
assertion-density gates (they are package glue), but still checked for silent
exception handling and circular dependencies.

Each gate maps to one or more Power-of-Ten rules:

    Rule 1  Simple control flow ............. no goto/setjmp/longjmp, no
                                              unbounded recursion, no metaprogramming
    Rule 2  Bounded loops ................... every loop provably terminates
    Rule 3  No dynamic allocation after init  no __import__/exec/eval at runtime
    Rule 4  Small functions ................. <= 50 logical lines (target)
    Rule 5  Assertion density ............... (advisory; Python favours exceptions)
    Rule 6  Smallest scope .................. no global/nonlocal, module state frozen
    Rule 7  Return values checked ........... (advisory; not statically decidable)
    Rule 8  Preprocessor limited ............ no exec/eval/compile abuse
    Rule 9  Pointers restricted ............. no globals()/locals(), shallow attr
    Rule 10 Zero warnings ................... ruff + mypy run elsewhere
    Rule 11 No silent exception handling ... no bare/Exception pass
    Rule 12 No magic global registries .... no mutable module-level collections
    Rule 13 No circular dependencies ....... acyclic import graph
    Rule 14 No god objects ................. bounded class size/responsibility
    Rule 15 No god functions ............... covered by Rule 4
"""

from __future__ import annotations

import ast
import os
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_PACKAGE = REPO_ROOT / "src" / "extraction_tool"
LEGACY_SCRIPTS = [REPO_ROOT / "preprocess_pdf.py", REPO_ROOT / "fetch_readings.py"]

# Functions above this line are hard failures. The JPL target is ~50 lines;
# this ceiling catches egregious god-functions while documenting the target.
FUNCTION_LENGTH_HARD_LIMIT = 200
FUNCTION_LENGTH_TARGET = 50

# Classes above this size are hard failures (no god objects).
CLASS_LINE_HARD_LIMIT = 400
CLASS_METHOD_HARD_LIMIT = 25


def _production_sources() -> list[Path]:
    """Return every production .py file to analyse."""
    paths: list[Path] = []
    if SRC_PACKAGE.is_dir():
        for root, _dirs, files in os.walk(SRC_PACKAGE):
            for name in files:
                if name.endswith(".py"):
                    paths.append(Path(root) / name)
    for legacy in LEGACY_SCRIPTS:
        if legacy.is_file():
            paths.append(legacy)
    return sorted(paths)


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return None


def _functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    funcs: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(node)
    return funcs


def _classes(tree: ast.AST) -> list[ast.ClassDef]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]


def _function_line_count(func: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    start = func.lineno
    end = func.end_lineno or start
    return end - start + 1


def _is_init(path: Path) -> bool:
    return path.name == "__init__.py"


# ─────────────────────────────────────────────────────────────────────────────
# Rule 1 + 8 + 9: Simple control flow / no metaprogramming / no forbidden calls
# ─────────────────────────────────────────────────────────────────────────────


def _forbidden_runtime_calls(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Find exec/eval/__import__ and unsafe compile inside a function body.

    ``re.compile`` is explicitly allowed: it compiles *regex* patterns, not
    arbitrary Python source, so it is not the C-preprocessor hazard Rule 8 bans.
    """
    hits: list[str] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        # re.compile is safe; other .compile() is the Rule 8 hazard.
        if isinstance(callee, ast.Attribute):
            if callee.attr in ("exec", "eval", "compile", "__import__"):
                # re.compile is safe; other .compile() is disallowed.
                if (
                    callee.attr == "compile"
                    and isinstance(callee.value, ast.Name)
                    and callee.value.id == "re"
                ):
                    continue
                hits.append(f"{callee.attr}() @L{node.lineno}")
            continue
        if isinstance(callee, ast.Name):
            if callee.id in ("exec", "eval", "__import__"):
                hits.append(f"{callee.id}() @L{node.lineno}")
            elif callee.id == "compile":
                # Bare compile() compiles source -> exactly the Rule 8 hazard.
                hits.append(f"compile() @L{node.lineno}")
    return hits


class TestSimpleControlFlow:
    def test_no_embedded_c_relocation_primitives(self):
        """Rule 1: no goto / setjmp / longjmp (or their Python equivalents)."""
        banned = {"goto", "setjmp", "longjmp"}
        for path in _production_sources():
            tree = _parse(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id in banned:
                    pytest.fail(
                        f"{path}:{node.lineno} forbidden control-flow "
                        f"primitive '{node.id}'"
                    )

    def test_no_unbounded_recursion_outside_algorithms(self):
        """Rule 1/3: direct self-recursion is banned except in algorithms/ (bounded DP).

        Only a *bare-name* call of the enclosing function counts as recursion
        (e.g. ``def fib(n): return fib(n-1) ...``). Method calls such as
        ``self._helper()`` or ``repo.extract(...)`` resolve to other objects and
        are not self-recursion.

        Exemptions (bounded, intentional recursion):
        - Functions under ``algorithms/`` (explicit memoized DP).
        - Nested local helpers (closures) such as tree-traversal ``walk``; their
          input is a strictly smaller sub-structure, so recursion is bounded.
        """
        for path in _production_sources():
            if "algorithms" in path.parts:
                continue
            tree = _parse(path)
            if tree is None:
                continue
            nested = self._nested_function_names(tree)
            for func in _functions(tree):
                if func.name in nested:
                    continue
                for node in ast.walk(func):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == func.name
                    ):
                        pytest.fail(
                            f"{path}:{func.lineno} function '{func.name}' "
                            f"recurses directly (Rule 1 bans uncontrolled recursion)"
                        )

    @staticmethod
    def _nested_function_names(tree: ast.AST) -> set[str]:
        """Names of functions defined inside another function body.

        Walks the tree building parent links so a function nested arbitrarily
        deep inside blocks (e.g. inside a ``try``) of another function is still
        recognised as a nested helper.
        """
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Walk up to the nearest enclosing function definition.
                p: ast.AST | None = parents.get(node)
                while p is not None and not isinstance(
                    p, (ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    p = parents.get(p)
                if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(node.name)
        return names

    def test_no_forbidden_runtime_calls(self):
        """Rules 3/8: no exec/eval/__import__/compile inside function bodies."""
        for path in _production_sources():
            tree = _parse(path)
            if tree is None:
                continue
            for func in _functions(tree):
                hits = _forbidden_runtime_calls(func)
                if hits:
                    pytest.fail(
                        f"{path}:{func.lineno} function '{func.name}' uses {hits}"
                    )


# ─────────────────────────────────────────────────────────────────────────────
# Rule 2: Bounded loops
# ─────────────────────────────────────────────────────────────────────────────


class TestBoundedLoops:
    def test_no_unprovably_bounded_while_true(self):
        """Rule 2: a ``while True`` must carry an explicit break/return bound.

        A ``while True`` whose body contains at least one ``break`` or ``return``
        is accepted as the standard stream-drain idiom; absence of either means
        the bound cannot be proven statically and the rule is violated.
        """
        for path in _production_sources():
            tree = _parse(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.While):
                    continue
                test = node.test
                is_true = isinstance(test, ast.Constant) and test.value is True
                if not is_true:
                    continue
                has_terminator = any(
                    isinstance(child, (ast.Break, ast.Return))
                    for child in ast.walk(node)
                )
                if not has_terminator:
                    pytest.fail(
                        f"{path}:{node.lineno} 'while True' has no provable "
                        f"termination (Rule 2 requires a static upper bound)"
                    )


# ─────────────────────────────────────────────────────────────────────────────
# Rule 4 / 15: Small functions (no god functions)
# ─────────────────────────────────────────────────────────────────────────────


class TestSmallFunctions:
    def test_function_length_within_hard_limit(self):
        """Rule 4: no function may exceed the hard length ceiling.

        The JPL target is ~50 logical lines. Functions above FUNCTION_LENGTH_TARGET
        but at or below FUNCTION_LENGTH_HARD_LIMIT are reported (not failed) so the
        team can decompose them incrementally. Anything above the hard limit is a
        gate failure.
        """
        over_target: list[str] = []
        for path in _production_sources():
            if _is_init(path):
                continue
            tree = _parse(path)
            if tree is None:
                continue
            for func in _functions(tree):
                n = _function_line_count(func)
                if n > FUNCTION_LENGTH_HARD_LIMIT:
                    pytest.fail(
                        f"{path}:{func.lineno} function '{func.name}' is {n} lines "
                        f"(hard limit {FUNCTION_LENGTH_HARD_LIMIT})"
                    )
                if n > FUNCTION_LENGTH_TARGET:
                    over_target.append(
                        f"{path}:{func.lineno} {func.name} ({n} lines)"
                    )
        if over_target:
            joined = "\n  ".join(over_target)
            warnings.warn(
                "Decomposition backlog (target <= "
                f"{FUNCTION_LENGTH_TARGET} lines):\n  {joined}",
                stacklevel=2,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Rule 6 + 12: Smallest scope / no magic global registries
# ─────────────────────────────────────────────────────────────────────────────


class TestSmallestScope:
    def test_no_global_or_nonlocal_keywords(self):
        """Rule 6: data must live at the smallest scope; no global mutation."""
        for path in _production_sources():
            tree = _parse(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.Global, ast.Nonlocal)):
                    pytest.fail(
                        f"{path}:{node.lineno} 'global'/'nonlocal' widens variable "
                        f"scope (Rule 6)"
                    )

    def test_no_mutated_module_level_registries(self):
        """Rule 12: module-level mutable collections used as registries are banned.

        Constant lookup tables (e.g. lists/sets of regex patterns) that are never
        mutated are permitted: they are frozen data, not registries. A collection
        is a "magic global registry" only if some function mutates it via
        ``.append/.add/.update/...``, subscript assignment, or ``del``.
        """
        for path in _production_sources():
            tree = _parse(path)
            if tree is None:
                continue
            mutable_names: set[str] = set()
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            mutable_names.add(target.id)
                elif (
                    isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Name)
                ):
                    mutable_names.add(node.target.id)
            if not mutable_names:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for child in ast.walk(node):
                        mut = self._mutation_of(child, mutable_names)
                        if mut:
                            pytest.fail(
                                f"{path}:{child.lineno} module-level collection "
                                f"'{mut}' is mutated inside a function (Rule 12)"
                            )

    @staticmethod
    def _mutation_of(node: ast.AST, names: set[str]) -> str | None:
        if isinstance(node, ast.Attribute) and isinstance(
            node.value, ast.Name
        ) and node.value.id in names:
            if node.attr in (
                "append",
                "extend",
                "insert",
                "remove",
                "pop",
                "clear",
                "update",
                "add",
                "discard",
                "sort",
                "reverse",
            ):
                return node.value.id
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id in names
        ):
            return node.value.id
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if (
                isinstance(tgt, ast.Subscript)
                and isinstance(tgt.value, ast.Name)
                and tgt.value.id in names
            ):
                return tgt.value.id
        elif isinstance(node, ast.Delete):
            for tgt in node.targets:
                if (
                    isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.value, ast.Name)
                    and tgt.value.id in names
                ):
                    return tgt.value.id
        elif (
            isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id in names
        ):
            return node.target.id
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Rule 9: Pointers restricted (no globals()/locals() introspection)
# ─────────────────────────────────────────────────────────────────────────────


class TestPointersRestricted:
    def test_no_globals_or_locals_introspection(self):
        """Rule 9: no globals()/locals() calls (opaque state access)."""
        banned = {"globals", "locals", "vars"}
        for path in _production_sources():
            tree = _parse(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in banned
                ):
                    pytest.fail(
                        f"{path}:{node.lineno} call to '{node.func.id}()' "
                        f"(Rule 9: opaque state access)"
                    )

    def test_no_deep_attribute_chains(self):
        """Rule 9: attribute dereference depth is bounded (<= 2 levels)."""
        for path in _production_sources():
            tree = _parse(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute):
                    continue
                depth = 0
                cur = node
                while isinstance(cur, ast.Attribute):
                    depth += 1
                    cur = cur.value
                if depth > 2:
                    pytest.fail(
                        f"{path}:{node.lineno} attribute chain depth {depth} "
                        f"(Rule 9 limits dereference to one level)"
                    )


# ─────────────────────────────────────────────────────────────────────────────
# Rule 11: No silent exception handling
# ─────────────────────────────────────────────────────────────────────────────


class _SilentHandler(Exception):
    """Raised internally when a silent except block is detected."""


def _is_silent_handler(handler: ast.ExceptHandler) -> str | None:
    """Return a reason string if *handler* swallows failure silently, else None.

    Bare ``except:`` and ``except Exception:`` (blanket) are forbidden when the
    body only ``pass``/``continue``/``break`` or returns None. Specific exception
    types (e.g. ``except ImportError``, ``except (LookupError, UnicodeError)``)
    are narrow by design and are permitted, as are ``return <error>`` results
    that carry a non-None signal to the caller.
    """
    caught = handler.type
    # Specific (non-blanket) exception types are allowed.
    if caught is not None and not (
        isinstance(caught, ast.Name) and caught.id == "Exception"
    ):
        return None
    body = handler.body
    if not body:
        return "empty handler"
    stmt = body[0]
    if isinstance(stmt, ast.Pass):
        return "silent 'except ...: pass'"
    if isinstance(stmt, (ast.Continue, ast.Break)):
        return "silent 'except ...: continue/break'"
    if isinstance(stmt, ast.Return):
        ret = stmt.value
        if ret is None or (isinstance(ret, ast.Constant) and ret.value is None):
            return "silent 'except ...: return None'"
    return None


class TestNoSilentExceptionHandling:
    def test_no_silent_except_blocks(self):
        """Rule 11: blanket ``except: pass`` / ``except Exception: pass`` is banned."""
        for path in _production_sources():
            tree = _parse(path)
            if tree is None:
                continue
            for handler in ast.walk(tree):
                if not isinstance(handler, ast.ExceptHandler):
                    continue
                reason = _is_silent_handler(handler)
                if reason:
                    pytest.fail(f"{path}:{handler.lineno} {reason} (Rule 11)")


# ─────────────────────────────────────────────────────────────────────────────
# Rule 13: No circular dependencies
# ─────────────────────────────────────────────────────────────────────────────


class TestNoCircularDependencies:
    def test_import_graph_is_acyclic(self):
        """Rule 13: the import graph must be acyclic."""
        graph: dict[str, set[str]] = {}
        for path in _production_sources():
            mod = self._module_name(path)
            if mod is None:
                continue
            graph.setdefault(mod, set())
            tree = _parse(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    dep = node.module
                    if dep.startswith("extraction_tool."):
                        graph[mod].add(dep)

        cycles = self._find_cycles(graph)
        if cycles:
            joined = "; ".join(" -> ".join(c) for c in cycles)
            pytest.fail(f"Circular dependencies detected: {joined}")

    @staticmethod
    def _module_name(path: Path) -> str | None:
        rel = path.relative_to(REPO_ROOT)
        if rel.parts[0] == "src":
            parts = rel.with_suffix("").parts[1:]
            return ".".join(parts)
        if path.name in ("preprocess_pdf.py", "fetch_readings.py"):
            return path.name[:-3]
        return None

    @staticmethod
    def _find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
        cycles: list[list[str]] = []
        visited: set[str] = set()
        stack: list[str] = []

        def dfs(node: str) -> None:
            visited.add(node)
            stack.append(node)
            for nxt in graph.get(node, set()):
                if nxt not in visited:
                    dfs(nxt)
                elif nxt in set(stack):
                    idx = stack.index(nxt)
                    cycles.append(stack[idx:] + [nxt])
            stack.pop()

        for node in list(graph):
            if node not in visited:
                dfs(node)
        return cycles


# ─────────────────────────────────────────────────────────────────────────────
# Rule 14: No god objects
# ─────────────────────────────────────────────────────────────────────────────


class TestNoGodObjects:
    def test_class_size_within_bounds(self):
        """Rule 14: classes must not accumulate unrelated responsibilities."""
        for path in _production_sources():
            if _is_init(path):
                continue
            tree = _parse(path)
            if tree is None:
                continue
            for cls in _classes(tree):
                start = cls.lineno
                end = cls.end_lineno or start
                lines = end - start + 1
                methods = [
                    n
                    for n in cls.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                if lines > CLASS_LINE_HARD_LIMIT:
                    pytest.fail(
                        f"{path}:{cls.lineno} class '{cls.name}' is {lines} lines "
                        f"(hard limit {CLASS_LINE_HARD_LIMIT})"
                    )
                if len(methods) > CLASS_METHOD_HARD_LIMIT:
                    pytest.fail(
                        f"{path}:{cls.lineno} class '{cls.name}' has {len(methods)} "
                        f"methods (hard limit {CLASS_METHOD_HARD_LIMIT})"
                    )


# ─────────────────────────────────────────────────────────────────────────────
# Rule 10: Zero warnings (delegate to ruff/mypy; assert they are wired)
# ─────────────────────────────────────────────────────────────────────────────


class TestZeroWarningsWired:
    def test_ruff_configuration_present(self):
        """Rule 10: a linter is configured (zero-warning tooling available)."""
        pyproject = REPO_ROOT / "pyproject.toml"
        assert pyproject.is_file(), "pyproject.toml must configure ruff/mypy"
        text = pyproject.read_text(encoding="utf-8")
        assert "[tool.ruff" in text, "ruff configuration missing"
        assert "[tool.mypy" in text, "mypy configuration missing"
