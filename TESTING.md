# Testing

```bash
python -m pip install -e ".[dev]"
ruff format --check .
ruff check .
mypy src
pytest
python -m build
```

The redirect suite uses urllib's real redirect/error dispatcher with a mocked
HTTP/HTTPS transport and synthetic DNS answers. No remote URLs or private
networks are contacted. Cover public-to-private redirects, IPv4/IPv6 literals,
mixed DNS answers, same-host relative redirects, changed DNS answers, all
supported redirect status codes (including Python 3.10 rejection of unsupported
308 responses), repeated/distinct-target hop limits, explicit
allow_private, response closure, batch continuation and strict failure.

The initial-only validation regression was reproduced against 1.1.0: an
in-memory public-to-private redirect was followed without a second policy check.
That case must now fail before the private transport is reached.

Verify the bundled offline README example and package versions in fresh wheel
and extracted-source installations. Compare packaged README, changelog,
development and testing guidance with source. DNS checks are not proof of
comprehensive SSRF prevention or control over transport resolution/proxies.

## Upper-bound regression

An in-memory chain with `max_redirects: 10000` reproduced an uncaught
`RecursionError` before the fix. Reject that configuration before DNS or
transport, accept exactly 20 successful hops, reject the next hop, and bound
both distinct-target and repeated-target chains at the documented maximum.

## 1.2.0 — capture provenance and bounded inputs

`allow_private` and `continue_on_error` must be JSON booleans. Malformed configurations, previous-capture structures and fixture metadata are rejected before DNS or requests. The default destination policy also blocks non-global and multicast DNS answers, and an empty answer is an error. Every network redirect retains the same address policy and 0–20 total-hop limit. Explicit `allow_private: true` keeps its intentional opt-in meaning; credentials in URLs are unsupported. DNS validation still does not pin the transport address or control proxies, so no comprehensive SSRF guarantee is made.

Inputs/documents are limited to 10 MiB each, JSON to 128 nesting levels and 1,000-digit integer tokens, documents to 100 and deduplicated URLs to 1,000. URLs are at most 8,192 characters. `max_bytes` is an integer from 1 through 50 MiB (default 5,000,000); `timeout` is a finite number above zero and at most 300 seconds (default 20). `captured_at` requires a full timestamp with seconds and UTC offset. Source paths and report/snapshot destinations reject symlinks; reports use exclusive creation in an existing parent directory. No existing source or report is replaced.

Each capture labels `capture_source` as `fixture` or `network` and whether its timestamp was supplied or obtained from the system UTC clock. Offline fixtures never perform DNS or requests, even when their supplied metadata names private addresses. Captures with identical bodies may share an immutable content-addressed raw file, but metadata is bound separately to the complete capture evidence. Identical evidence can be reused only after byte verification; changed or corrupt existing files are never overwritten. A later write error can leave earlier new snapshot files; captures and reports are not a multi-file transaction.

Previous reports require an explicit captures array with unique requested URLs. Minimal legacy capture fragments remain supported. `unchanged` refers only to the captured byte prefix and final URL; it is not proof that a complete remote representation or its semantics remained unchanged. Each comparison states whether two explicitly untruncated representations were compared. HTML canonical relations are matched as tokens, and declared HTML charsets are respected when available. Markdown renders capture URLs/errors literally.

The shipped offline sample is under `share/doc/linkwitness/examples/sample.json` in the installation prefix. Full release acceptance requires the original supported native matrix, CodeQL/build and the added dependency audit, then actual tag-built installed examples and distributions. No authentication, rendering engine or crawling is added.
