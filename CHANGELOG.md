# Changelog

## 1.2.0 - 2026-10-21

- Treat failed prior captures as unavailable comparison evidence, including contradictory legacy metadata.

- Validate capture configuration and DNS answers without weakening private-target or redirect boundaries.
- Bind immutable snapshot metadata to each capture and label fixture/network provenance.
- Bound strict JSON/document inputs and preserve existing reports and evidence files.
- Clarify truncated/legacy comparisons, improve HTML metadata parsing and render literal Markdown.
- Add dependency audit coverage and official tag-built distribution checksums.

## 1.1.1 - 2026-10-16

- Apply the existing private-target policy to every redirect before opening the next request, including relative redirects and mixed DNS answers.
- Add a configurable total redirect-hop limit from 0 through 20 (default 10), validated before requests to keep urllib recursion bounded while preserving explicit private-target access and batch/strict behavior.
- Add mocked redirect regressions and document the DNS/transport policy boundary.

## 1.1.0 - 2026-07-27

- Added URL extraction from saved documents, normalized deduplication, capture timestamps, full redirect-chain records, selected response validators, HTML descriptions and canonical links, and configurable response-size and timeout limits.
- Added private-network blocking by default, batch error records, deterministic fixtures, raw snapshot metadata, and explicit truncation reporting.
- Added comparison with previous capture reports to identify new, changed, unchanged, missing, and failed links.

## 1.0.0 - 2026-07-26

- Released the first complete LinkWitness command-line workflow.
- Added deterministic JSON and Markdown reporting, representative examples, and cross-platform tests.
