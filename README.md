# LinkWitness

[![CI](https://github.com/loganpendragonmultiverse/linkwitness/actions/workflows/ci.yml/badge.svg)](https://github.com/loganpendragonmultiverse/linkwitness/actions/workflows/ci.yml)

Create reviewable web-link evidence from explicit URLs or URLs extracted from saved text and Markdown documents. Version 1.2.0 records capture time, redirect history, response validators, metadata, content fingerprints, truncation, optional raw snapshots, batch errors, and changes from a previous capture.

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

A network capture records what this client received at one recorded moment; fixture captures record operator-supplied synthetic data. It does not prove authorship, legal admissibility, long-term availability, or semantic equivalence. JavaScript rendering, authenticated browsing, and crawler-style discovery remain outside scope. Offline fixture captures carry an explicit fixture marker; supplied response metadata does not verify any network target.

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
to an integer from 0 through 20 inclusive in the JSON input; `0`
permits the initial request but follows no redirects. All followed redirects
count, including repeated URLs in loops. Because urllib follows redirects
recursively, values outside 0–20 are rejected before DNS lookup or any request. Relative locations resolve against the
current URL, then undergo the same HTTP/HTTPS and address checks before another
request is opened. HTTP 308 support follows the installed Python urllib;
Python 3.10 reports an unsupported 308 response without following it. Batch captures record a blocked target or exceeded limit as
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

## 1.2.0 — capture provenance and bounded inputs

`allow_private` and `continue_on_error` must be JSON booleans. Malformed configurations, previous-capture structures and fixture metadata are rejected before DNS or requests. The default destination policy also blocks non-global and multicast DNS answers, and an empty answer is an error. Every network redirect retains the same address policy and 0–20 total-hop limit. Explicit `allow_private: true` keeps its intentional opt-in meaning; credentials in URLs are unsupported. DNS validation still does not pin the transport address or control proxies, so no comprehensive SSRF guarantee is made.

Inputs/documents are limited to 10 MiB each, JSON to 128 nesting levels and 1,000-digit integer tokens, documents to 100 and deduplicated URLs to 1,000. URLs are at most 8,192 characters. `max_bytes` is an integer from 1 through 50 MiB (default 5,000,000); `timeout` is a finite number above zero and at most 300 seconds (default 20). `captured_at` requires a full timestamp with seconds and UTC offset. Source paths and report/snapshot destinations reject symlinks; reports use exclusive creation in an existing parent directory. No existing source or report is replaced.

Each capture labels `capture_source` as `fixture` or `network` and whether its timestamp was supplied or obtained from the system UTC clock. Offline fixtures never perform DNS or requests, even when their supplied metadata names private addresses. Captures with identical bodies may share an immutable content-addressed raw file, but metadata is bound separately to the complete capture evidence. Identical evidence can be reused only after byte verification; changed or corrupt existing files are never overwritten. A later write error can leave earlier new snapshot files; captures and reports are not a multi-file transaction.

Previous reports require an explicit captures array with unique requested URLs. Minimal legacy capture fragments remain supported. `unchanged` refers only to the captured byte prefix and final URL; it is not proof that a complete remote representation or its semantics remained unchanged. Each comparison states whether two explicitly untruncated representations were compared. HTML canonical relations are matched as tokens, and declared HTML charsets are respected when available. Markdown renders capture URLs/errors literally.

The shipped offline sample is under `share/doc/linkwitness/examples/sample.json` in the installation prefix. Full release acceptance requires the original supported native matrix, CodeQL/build and the added dependency audit, then actual tag-built installed examples and distributions. No authentication, rendering engine or crawling is added.

## 1.2.1: Release artifact verification

The tag workflow checks that the stable tag, project metadata and runtime version agree before building. It runs the full existing quality suite and dependency audit, verifies wheel and source-distribution metadata, and writes SHA256SUMS from those exact two payloads. Native PR/main checks and independent installed-artifact acceptance remain required before publication. This maintenance release preserves runtime behavior and supported Python versions.
