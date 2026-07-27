# LinkWitness

[![CI](https://github.com/loganpendragonmultiverse/linkwitness/actions/workflows/ci.yml/badge.svg)](https://github.com/loganpendragonmultiverse/linkwitness/actions/workflows/ci.yml)

Create reviewable web-link evidence from explicit URLs or URLs extracted from saved text and Markdown documents. Version 1.1 records capture time, redirect history, response validators, metadata, content fingerprints, truncation, optional raw snapshots, batch errors, and changes from a previous capture.

## Three-minute start

```bash
python -m pip install .
linkwitness examples/sample.json
linkwitness examples/sample.json --format json --output evidence.json
```

Snapshots are opt-in and saved locally as a raw response plus a JSON metadata sidecar. Multiple URLs are deduplicated while preserving their first-seen order.

## Capture and safety model

- Only explicit HTTP and HTTPS links are accepted.
- Private, loopback, link-local, and reserved network targets are blocked by default.
- Response size and timeout limits are configurable and truncation is explicit.
- Redirect hops, final URL, status, content type, ETag, Last-Modified, title, description, canonical link, byte count, and SHA-256 are recorded where available.
- Batch failures become evidence records by default; strict mode can stop at the first failure.
- A previous report classifies links as new, changed, unchanged, missing, or failed.

## Interpretation boundary

A capture proves what this client received at one recorded moment. It does not prove authorship, legal admissibility, long-term availability, or semantic equivalence. JavaScript rendering, authenticated browsing, and crawler-style discovery remain outside scope. Fixtures exist for deterministic tests and clearly identify themselves through supplied headers.

Python 3.10 or newer is supported on Windows, macOS, and Linux with no runtime dependencies, telemetry, account, or hosted service.

## Development

```bash
python -m pip install -e ".[dev]"
ruff format --check .
ruff check .
mypy src
pytest
python -m build
```

Part of the [Logan Pendragon Forge open-source collection](https://www.loganpendragonforge.com/open-source/). Licensed under the [MIT License](LICENSE).
