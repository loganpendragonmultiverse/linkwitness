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
