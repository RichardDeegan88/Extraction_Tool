# Architecture

This package is a `src/`-layout refactor of the original two root scripts
(`preprocess_pdf.py`, `fetch_readings.py`) using the Data Access Factory (DAF)
pattern from [RAliane-REBORN/theDAF](https://github.com/RAliane-REBORN/theDAF).

The root scripts remain as **thin compatibility wrappers** so the existing test
suite (`import preprocess_pdf`, `import fetch_readings`) keeps working. They
re-export symbols and delegate to the package.

## Layer model

```
                  DataAccessFactory   (composition only; no HTTP, no algorithms)
                          |
                          v
                      DataAccess      (async query / post / put / delete)
                          |
              +-----------+-----------+
              |                       |
        Repository                 Algorithm
              |                       |
            Cache                 (explicit memo)
```

Application domain operations (PDF extraction, reading acquisition) live in
**Services**, which the transport adapters call directly. `DataAccess` is the
generic CRUD orchestration boundary; it is *not* used for domain extraction
logic (see `adapters/fastapi.py` docstring).

| Layer | Module | Responsibility |
|---|---|---|
| Factory | `core/factory.py` | Build `DataAccess` from explicit dependencies |
| DataAccess | `core/access.py` | Generic async `query/post/put/delete` + caching |
| Protocols | `core/protocols.py` | `Repository`, `Cache`, `Algorithm`, `Authorizer` |
| Errors | `core/errors.py` | `NotFoundError`, `ValidationError`, `AuthorizationError` |
| Contracts | `contracts/` | Pydantic v2 boundary models (query, extraction, readings, results) |
| Repositories | `repositories/` | Filesystem, HTTP, in-memory external access |
| Cache | `cache/` | Reusable state (get/set/delete/clear) |
| Algorithms | `algorithms/dynamic_programming.py` | Explicit-memoized computation |
| Extraction | `extraction/` | PDF, OCR, validation, normalization, HTML |
| Services | `services/` | Domain orchestration (extraction, reading) |
| Adapters | `adapters/cli.py`, `adapters/fastapi.py` | Transport only |

## Invariants

- **FastAPI is transport only.** Route handlers do request reception, Pydantic
  validation, rate-limit enforcement, service invocation, response serialization.
  No extraction / repository / cache / algorithm / filesystem / HTTP-client logic.
- **CLI is transport only.** `adapters/cli.py` calls the same `ExtractionService`
  / `ReadingService` as FastAPI. No duplicated extraction behavior.
- **Pydantic validates the boundary.** External inputs come in as explicit typed
  contracts, never raw dictionaries.
- **Factory composes; it does not execute.** No HTTP calls or algorithms inside
  `DataAccessFactory`.
- **Repositories isolate I/O.** The core never performs `requests`/network calls
  inline in business functions.
- **Cache is deterministic** with explicit invalidation (`delete`/`clear`).

## Optional dependency strategy

`bs4`, `selenium`, `fastapi`, `slowapi`, and `trafilatura` are **optional**. They
are lazy-imported inside `try/except` where used, so the package imports and runs
without them. `mypy` tolerates the `type: ignore[import-not-found]` comments via
`warn_unused_ignores = false`, keeping type checks green whether or not the
optional extras are installed. Tests guard optional layers with
`pytest.importorskip`.

Extraction chain for article text (in `ReadingService` / `extraction/html.py`):

```
trafilatura (primary)  ->  bs4 (middle)  ->  built-in stripper (last resort)
```

Each tier is accepted only above the 50-word threshold. All tiers flow through
`normalization.sanitize()` for invisible/bidi character stripping.

## Security invariants (preserved from the baseline)

- **SSRF blocking** — `repositories/http.py::_is_public_host()` refuses loopback,
  private, link-local, multicast, and reserved IPs; `_SafeRedirectHandler` refuses
  non-HTTP(S) and private-host redirects. The same check runs *before* launching
  a Selenium browser in `fetch_rendered_html`.
- **Atomic writes** — `_atomic_write_text` / `_atomic_write_bytes` write a `.tmp`
  sibling and rename; the temp file is removed on failure.
- **Sanitization parity** — invisible/bidi/tag-block codepoint sets are shared
  between `preprocess_pdf` and `fetch_readings` via `normalization.sanitize()`.

## Dynamic programming

`algorithms/dynamic_programming.py` implements Fibonacci with **explicit**
memoization (a `dict`, not `functools.lru_cache`), tracking `iterations` and
`cache_hits`. It has explicit termination and exposes deterministic stats.

## Complexity / JPL Power-of-Ten

Functions target ≤50 logical lines. A small number of service/extraction
functions exceed this (e.g. `ReadingService.acquire_readings`,
`ExtractionService.extract_pdf`, `format_quality_header`) and are tracked as a
**decomposition backlog** (see `tests/test_power_of_ten.py` warnings). They are
bounded, with explicit failure handling and no silent `except: pass`.

## Testing

- `pytest tests/` — unit + integration; synthetic PDFs via `tests/conftest.py`.
- Power-of-Ten AST gates: `tests/test_power_of_ten.py`.
- DAF components: `tests/test_daf_components.py`.
- FastAPI behavior + rate limiting: `tests/test_fastapi_adapter.py` (runs only
  when the `api` extra is installed).
- Optional layers (`bs4`, `selenium`, `trafilatura`) are `importorskip`-guarded.
