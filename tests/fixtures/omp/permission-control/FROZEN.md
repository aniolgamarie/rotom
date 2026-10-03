# Frozen permission-control fixture

- Review state: `accepted and frozen by maintainer`
- Schema version: `1`
- Candidate generated on: `2026-09-29`, before rule implementation or model evaluation
- Cases: `240` (`policy-safe=100`, `ask-deny=100`, `fault-state=40`)
- Safe decision sources: `low-risk-rule=40`, `reviewer=60`
- Compound: `policy-safe=50`, `ask-deny=40`
- Candidate tree SHA-256: `4e7df262ccefc32c816317d47ffdf9336fb880c15f7c7a87e3b68ac2f0d127b6`

## Digest boundary

The digest covers exactly these paths in lexicographic order: `fixture-schema.json`, `cases.jsonl`, and `labels.json`. For each path, SHA-256 consumes `UTF-8(relative path)`, one NUL byte, the exact file bytes, and one NUL byte. This file is excluded to avoid self-reference. Native baseline results, acceptance records, and later runtime fixtures are excluded.

## Review correction

The earlier candidates `f26cecfa45c8432256cf3e6073b2bad9f1d6ef559c33b8a240852e244cf91e19` and `7c5aeea45a4930adf489a223224eff035351d076863cd913c294cdbb02ec8b6c` failed pre-implementation label review. They were replaced before any rule implementation, model evaluation, or sample execution. The first overused numbered templates and had inconsistent risk/fault priorities; the second included commands outside the first-release allowlist, an unresolved glob target, and incorrect fallback/source-chain labels. This correction is not relabeling in response to implementation or model results.

## Freeze rule

Commands and event sequences are data and must never be executed during generation or validation. After maintainer acceptance, evaluation failures must not be removed, relabeled, or hidden by backfilling cases. An intentional later revision requires a reviewed new identity and must not be presented as this baseline.
