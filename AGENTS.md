# AGENTS.md — Extraction Toolkit

## Current State

This repo is being refactored from two root-level scripts (`preprocess_pdf.py`, `fetch_readings.py`) into a `src/`-layout package with a Data Access Factory (DAF) architecture sourced from [RAliane-REBORN/theDAF](https://github.com/RAliane-REBORN/theDAF).

The existing scripts are the **behavioral baseline**. Do not silently change:
- CLI flags, positional arguments, or exit codes
- output formats, quality headers, or `--- PAGE N ---` markers
- OCR `[OCR]` / `[BLANK]` tags
- `MANUAL_CAPTURE.txt` content and routing rules
- page-count validation, missing-page reporting, and sequence checks
- paywall / gated-content handling

## Commands

```bash
python preprocess_pdf.py --check          # preflight: verify poppler, tesseract, imagemagick, pypdf
pytest tests/                             # run suite (synthetic PDFs, no network needed for most tests)
```

Tests import the root scripts as modules (`import preprocess_pdf`, `import fetch_readings`). They use reportlab + Pillow fixtures in `tests/conftest.py`. Some tests skip when `pdftotext` or `tesseract` is absent.

## Target Structure

Use src layout:

```
src/
    extraction_tool/
        __init__.py
        core/
            __init__.py
            access.py
            factory.py
            protocols.py
            errors.py
        contracts/
            __init__.py
            query.py
            extraction.py
            readings.py
            results.py
        repositories/
            __init__.py
            base.py
            filesystem.py
            http.py
            memory.py
        extraction/
            __init__.py
            pdf.py
            validation.py
            ocr.py
            normalization.py
        algorithms/
            __init__.py
            dynamic_programming.py
        cache/
            __init__.py
            base.py
            memory.py
        adapters/
            __init__.py
            fastapi.py
            cli.py
        services/
            __init__.py
```

Only create a module when it has a distinct responsibility.

## Architecture Invariant

```
DataAccessFactory
        |
        v
   DataAccess
        |
   +----+----+
   |         |
Repository  Algorithm
   |
  Cache
```

Apply the following layer responsibilities. No layer may silently absorb another's responsibility:

- **FastAPI** handles transport only. When present, it is an adapter over DataAccess.
- **CLI** handles command-line transport only. It calls the same DataAccess/service layer as other adapters. Do not duplicate extraction behavior inside the CLI.
- **Pydantic** handles boundary validation.
- **DataAccess** handles application operations.
- **Repository** handles external/data-source access.
- **Cache** handles reusable state.
- **Algorithms** handle computation.
- **Extraction modules** handle document extraction.
- **Factory** handles dependency composition.

## Data Access Contract

Implement a typed DataAccess interface with operations:

- `query()`
- `post()`
- `put()`
- `delete()`

These operations are asynchronous at the DataAccess boundary.

Concrete operation types MUST be represented by explicit typed contracts. Do not use dictionaries as the primary application interface. Do not use `Any` as a substitute for proper contracts.

## Factory Contract

Implement `DataAccessFactory`. The factory constructs DataAccess instances and is responsible for composition. The factory is NOT responsible for performing HTTP operations or implementing extraction algorithms. Dependencies must be explicit. Do not use singleton global state or hidden dependency discovery.

## Extraction Operations

Model extraction as explicit operations with explicit input, explicit output, and explicit failure behavior. At minimum distinguish:

- PDF acquisition
- PDF preprocessing
- text extraction
- OCR detection
- page validation
- text normalization
- reading acquisition
- result validation

## PDF Invariants

Preserve existing PDF quality guarantees. The system must explicitly represent:

- expected page count
- observed page count
- missing pages
- OCR status
- extraction status
- extraction errors

Never silently treat partial extraction as successful extraction.

## Reading Acquisition

External reading acquisition must be isolated behind a repository or source abstraction. The core application must not directly depend on requests made from inside arbitrary business functions.

Failures such as network failure, timeout, HTTP failure, paywall, malformed response, and unsupported content must become explicit typed outcomes or domain errors. Do not silently swallow failures.

## Optional Scraping Layers (bs4 / Selenium)

`beautifulsoup4` and `selenium` are optional extraction layers, installed via the
`scraping` and `browser` dependency groups respectively. They are not core
dependencies and must remain lazy-imported so the package works without them
(`pytest.importorskip` guards their tests).

- **bs4** is the middle tier of the article extraction chain in
  `ReadingService` / `extraction/html.py`: trafilatura (primary) → bs4 →
  built-in stripper (last resort). Each tier is accepted only above the 50-word
  threshold. Keep this order; do not promote bs4 above trafilatura.
- **Selenium** is opt-in only via `ReadingRequest.use_browser`. The repository
  method `HttpReadingRepository.fetch_rendered_html` owns all browser I/O and
  must run the same `_is_public_host()` SSRF check BEFORE launching the browser.
  The WebDriver is created inside the method (never at module level) so no
  private host is ever reached and no global mutable browser state exists.
- Both paths still flow through `normalization.sanitize()` for invisible-character
  stripping, and the SSRF / atomic-write invariants from `fetch_readings.py` apply
  unchanged.

## Cache

Define a cache abstraction with operations: get, set, delete, clear. Cache behavior must be deterministic. Cache invalidation must be explicit. Do not introduce a cache merely to hide expensive or badly structured code.

## Dynamic Programming

Implement the dynamic-programming demonstration using recursion and explicit memoization. Do NOT use `functools.lru_cache` as the primary implementation. Use explicit memo state and expose deterministic execution statistics: at minimum `iterations` and `cache_hits`. The algorithm must have explicit termination conditions, no uncontrolled recursion, and no unbounded recursive input.

## JPL Power-of-Ten Constraints

1. Simple control flow. Avoid deeply nested branching.
2. Bounded loops. Every loop must have an identifiable termination condition.
3. Bounded recursion. Recursive algorithms must have explicit termination and bounded input.
4. Small functions. Functions exceeding approximately 50 logical lines require explicit justification and decomposition analysis.
5. Limited branching. Avoid excessive conditional complexity.
6. Explicit state. Do not hide important state in global variables.
7. Restricted mutable state. Prefer immutable values and local state.
8. Explicit dependencies. Dependencies must enter through constructors or function parameters.
9. Deterministic failure. Errors must have defined propagation paths.
10. No clever control flow. Do not use metaprogramming, dynamic execution, or opaque reflection where a direct implementation is possible.
11. No silent exception handling. `except Exception: pass` or equivalent patterns are forbidden.
12. No magic global registries. Dependency registration must be explicit.
13. No circular dependencies. Dependency direction must remain acyclic.
14. No god objects. A class must not accumulate unrelated responsibilities.
15. No god functions. Large workflows must be decomposed into independently testable stages.

## Complexity Gates

Target:

- functions <= 50 logical lines
- low cyclomatic complexity
- shallow nesting
- explicit recursion bounds
- explicit loop termination
- no global mutable application state

### Enforced as automated gates

The JPL Power-of-Ten rules and the complexity targets above are enforced as
mechanical AST-analysis gates in `tests/test_power_of_ten.py`. They run as part
of `pytest tests/` and (for Rule 10) under the `lint` job in CI. Each test class
maps to one or more rules:

| Gate | Rule(s) |
|---|---|
| `TestSimpleControlFlow` | 1, 3, 8 — no goto/setjmp/longjmp, no uncontrolled recursion, no exec/eval/__import__/compile (re.compile allowed) |
| `TestBoundedLoops` | 2 — every loop provably terminates |
| `TestSmallFunctions` | 4, 15 — functions within hard ceiling; >50 lines is a decomposition backlog |
| `TestSmallestScope` | 6, 12 — no global/nonlocal, no mutated module-level registries |
| `TestPointersRestricted` | 9 — no globals()/locals(), attribute depth <= 2 |
| `TestNoSilentExceptionHandling` | 11 — no blanket `except: pass` / `except Exception: pass` |
| `TestNoCircularDependencies` | 13 — acyclic import graph |
| `TestNoGodObjects` | 14 — bounded class size/responsibility |
| `TestZeroWarningsWired` | 10 — ruff + mypy configured |

Scope: `src/extraction_tool/**`, `preprocess_pdf.py`, `fetch_readings.py`.
`tests/**` is exempt (not shipped). `__init__.py` is exempt from length/assertion
gates. `algorithms/**` and nested local helpers are exempt from the recursion ban
(bounded, memoized DP / tree traversal).

If an existing behavior requires violating a constraint:

1. document the reason
2. isolate the violation
3. prevent propagation
4. add a test
5. record it as technical debt

Do not simply disable the constraint.

## FastAPI

FastAPI is an adapter. Implement REST primitives: GET, POST, PUT, DELETE. Endpoints must perform only request reception, Pydantic validation, rate-limit enforcement, DataAccess invocation, and response serialization. Route handlers MUST NOT contain extraction logic, repository logic, cache logic, algorithm logic, filesystem logic, or HTTP client logic. Use endpoint-level rate limiting. Suggested defaults: GET 30/minute, POST 10/minute, PUT 10/minute, DELETE 10/minute. Rate limiting must not exist inside DataAccess.

## Pydantic

All external inputs must be validated with Pydantic v2. Use explicit models. Do not pass raw dictionaries through the application architecture. Do not duplicate boundary validation unnecessarily.

## CLI

Preserve the existing CLI behavior. Move CLI implementation behind `adapters/cli.py`. The CLI must call the same DataAccess/service layer as other adapters. Do not duplicate extraction behavior inside the CLI.

## Test Strategy

Maintain green tests continuously. Before completion, run:

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy src
uv build --no-sources
```

Add tests for DataAccessFactory, DataAccess, repositories, cache, PDF extraction, page validation, OCR detection, normalization, reading acquisition, failure propagation, DP recursion, DP memoization, CLI behavior, FastAPI behavior, and rate limiting.

## Behavioral Equivalence

For every major refactor, verify same input produces equivalent result. Compare extracted text, page counts, error reporting, OCR status, missing-page detection, reading acquisition results, and CLI exit behavior. Do not accept "the tests still pass" as the only validation. Where practical, establish golden fixtures.

## Agent Loop

Proceed incrementally. For every architectural migration:

```
INSPECT -> DEFINE CONTRACT -> IMPLEMENT -> TEST -> STATIC ANALYSIS -> VERIFY BEHAVIOR -> NEXT COMPONENT
```

Do not perform an uncontrolled repository-wide rewrite. Never delete working functionality merely to simplify the refactor.

## Git Discipline

Work in small logical commits. Suggested progression:

1. baseline characterization
2. packaging
3. contracts
4. repository abstraction
5. extraction decomposition
6. cache abstraction
7. DataAccess
8. Factory
9. CLI adapter
10. FastAPI adapter
11. architectural linting
12. documentation

Do not mix unrelated changes.

## Final Validation

Before completion, verify:

- package installation
- CLI execution
- PDF extraction
- reading acquisition
- failure reporting
- FastAPI endpoints
- endpoint rate limits
- memoization
- architectural boundaries

Inspect the final dependency graph. Confirm that core does not import FastAPI, extraction does not import FastAPI, algorithms do not import FastAPI, repositories do not depend on route handlers, route handlers do not contain business logic, no global mutable state exists, no uncontrolled recursion exists, and no silent exception handling exists.

Report baseline LOC, final LOC, module count, test count, coverage if available, complexity changes, architectural violations removed, remaining exceptions, performance changes, behavioral changes, and known technical debt. Do not claim the refactor is complete if any validation step fails.

The objective is not minimum LOC. The objective is deterministic behavior, explicit boundaries, bounded complexity, testable components, replaceable dependencies, predictable agent-generated modifications, and preserved extraction correctness.

## Security Invariants

`fetch_readings.py` has SSRF prevention: `_is_public_host()` blocks loopback, private, link-local, multicast, and reserved IPs; `_SafeRedirectHandler` refuses non-HTTP(S) redirects and private-hosts redirects. Any refactor of fetching must preserve these checks exactly.

Both scripts share invisible/bidi/tag-block character sanitization (identical codepoint sets). Keep them in sync; a drift is a security regression.

## Atomic Writes

`_atomic_write_text` and `_atomic_write_bytes` write to a `.tmp` sibling then rename. On failure the temp file is removed. Do not replace with naive `write_text`/`write_bytes`.

## Version

Read from the `VERSION` file in the repo root (`1.2.1`). Do not hard-code.

## Key Files

| Path | Role |
|---|---|
| `preprocess_pdf.py` | PDF extraction, OCR fallback, heading index, quality report |
| `fetch_readings.py` | Syllabus URL extraction, fetching, gating, MANUAL_CAPTURE |
| `tests/conftest.py` | Synthetic PDF fixtures (simple, header/footer, outline, junk metadata, image-only) |
| `tests/test_preprocess_pdf.py` | Extraction, cleaning, headings, OCR lang validation, CLI, atomic writes |
| `tests/test_fetch_readings.py` | Categorisation, gating, SSRF blocking, bounded downloads, atomic writes |

## What Not To Do

- Do not run two extraction instances against the same output folder.
- Do not pass `--overwrite` unless explicitly requested.
- Do not commit `.txt`, `.pdf`, or `extracted/` outputs.
- Do not bypass paywalls or attempt to fetch paywalled/institutional-proxy readings.
- Do not publish or redistribute extracted text.
