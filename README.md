# LinkWitness

[![CI](https://github.com/loganpendragonmultiverse/linkwitness/actions/workflows/ci.yml/badge.svg)](https://github.com/loganpendragonmultiverse/linkwitness/actions/workflows/ci.yml)

Create reviewable web-link evidence from explicit URLs or URLs extracted from saved text and Markdown documents. Version 1.1.1 records capture time, redirect history, response validators, metadata, content fingerprints, truncation, optional raw snapshots, batch errors, and changes from a previous capture.

## Three-minute start

```bash
python -m pip install .
linkwitness examples/sample.json
linkwitness examples/sample.json --format json --output evidence.json
```

Snapshots are opt-in and saved locally as a raw response plus a JSON metadata sidecar. Multiple URLs are deduplicated while preserving their first-seen order.

## Capture and safety model

- Only explicit HTTP and HTTPS links are accepted.
- The existing private, loopback, link-local, and reserved address policy is checked on the starting URL and before every HTTP redirect is followed. A mixed DNS answer is blocked if any returned address matches that policy.
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

## Redirect policy and limits

Network captures allow at most 10 redirect hops by default. Set `max_redirects`
to a nonnegative integer in the JSON input to choose the total limit; `0`
permits the initial request but follows no redirects. All followed redirects
count, including repeated URLs in loops. Relative locations resolve against the
current URL, then undergo the same HTTP/HTTPS and address checks before another
request is opened. Batch captures record a blocked target or exceeded limit as
an error and continue; `continue_on_error: false` stops with a capture error.

An explicit `allow_private: true` keeps its existing meaning for both the
starting URL and redirects. It does not disable the HTTP/HTTPS restriction or
the redirect limit. Offline `fixtures` perform no requests or DNS lookups;
their supplied redirect metadata is not a network-policy verification.

These checks inspect DNS answers before requests; the underlying HTTP transport
can resolve the host again when connecting. They do not pin connection addresses,
prevent DNS changes after a check, control proxy routing, or provide comprehensive
SSRF protection. The tests exercise mocked address answers and redirects,
including mixed IPv4/IPv6 answers. No private-network probes are used.
