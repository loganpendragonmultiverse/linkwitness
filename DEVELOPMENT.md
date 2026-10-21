# Development contract

Capture redirect, metadata, content fingerprint, and optional snapshot evidence for supplied web links.

Preserve deterministic, source-safe behavior and the interpretation boundary documented in the README. Every feature release must update tests, version metadata, `CHANGELOG.md`, README claims and limitations, repository metadata, release assets, and the Forge catalog together.

## Redirect policy correction

Keep the report schema and explicit `allow_private` behavior compatible.
Validate resolved redirect URLs before following them and use one total-hop
counter across repeated and distinct targets. Do not infer complete SSRF
protection from hostname checks: transport DNS and proxy behavior remain
outside this bounded policy. Tests use synthetic DNS and in-memory responses.

The supported `max_redirects` range is 0 through 20, with default 10.
Validate the range before any request and when constructing a redirect handler;
do not raise urllib's recursive guards to an unbounded user value.

## 1.2.0 — capture provenance and bounded inputs

`allow_private` and `continue_on_error` must be JSON booleans. Malformed configurations, previous-capture structures and fixture metadata are rejected before DNS or requests. The default destination policy also blocks non-global and multicast DNS answers, and an empty answer is an error. Every network redirect retains the same address policy and 0–20 total-hop limit. Explicit `allow_private: true` keeps its intentional opt-in meaning; credentials in URLs are unsupported. DNS validation still does not pin the transport address or control proxies, so no comprehensive SSRF guarantee is made.

Inputs/documents are limited to 10 MiB each, JSON to 128 nesting levels and 1,000-digit integer tokens, documents to 100 and deduplicated URLs to 1,000. URLs are at most 8,192 characters. `max_bytes` is an integer from 1 through 50 MiB (default 5,000,000); `timeout` is a finite number above zero and at most 300 seconds (default 20). `captured_at` requires a full timestamp with seconds and UTC offset. Source paths and report/snapshot destinations reject symlinks; reports use exclusive creation in an existing parent directory. No existing source or report is replaced.

Each capture labels `capture_source` as `fixture` or `network` and whether its timestamp was supplied or obtained from the system UTC clock. Offline fixtures never perform DNS or requests, even when their supplied metadata names private addresses. Captures with identical bodies may share an immutable content-addressed raw file, but metadata is bound separately to the complete capture evidence. Identical evidence can be reused only after byte verification; changed or corrupt existing files are never overwritten. A later write error can leave earlier new snapshot files; captures and reports are not a multi-file transaction.

Previous reports require an explicit captures array with unique requested URLs. Minimal legacy capture fragments remain supported. `unchanged` refers only to the captured byte prefix and final URL; it is not proof that a complete remote representation or its semantics remained unchanged. Each comparison states whether two explicitly untruncated representations were compared. HTML canonical relations are matched as tokens, and declared HTML charsets are respected when available. Markdown renders capture URLs/errors literally.

The shipped offline sample is under `share/doc/linkwitness/examples/sample.json` in the installation prefix. Full release acceptance requires the original supported native matrix, CodeQL/build and the added dependency audit, then actual tag-built installed examples and distributions. No authentication, rendering engine or crawling is added.

## 1.2.1: Release artifact verification

The tag workflow checks that the stable tag, project metadata and runtime version agree before building. It runs the full existing quality suite and dependency audit, verifies wheel and source-distribution metadata, and writes SHA256SUMS from those exact two payloads. Native PR/main checks and independent installed-artifact acceptance remain required before publication. This maintenance release preserves runtime behavior and supported Python versions.
