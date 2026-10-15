# Release-preparation verification

Date: 2026-10-15. This record covers the English documentation/privacy preparation and narrow manager fixes. It does not renew historical native or live-account acceptance. Platform: **Linux x86_64, CPython 3.11.11**. Other operating systems and remote CI were not executed in this preparation.

## Source and lock scope

The full offline regression used the Python snapshot integrated at `69cf610` (documentation HEAD at start: `4ec53be`; later documentation-only commit `c7e9049`). Its Python, workflow, and lock digests remained unchanged during the run. The aggregate Python digest was `92227e42c702b30ae94defe6976592a00e0c1dc111f75ed609d5f32ffe81791e` under the local runner's recorded file-list/hash scheme.

The final runtime-code snapshot is `128aeadd`; `8b6df9c` changes only the public checker test's synthetic path construction, preserving its runtime value. These final changes have separate affected checks below. The full-suite result is not relabeled as a run of those later commits.

| Dependency | Final check |
| --- | --- |
| DSH | PASS; lock `bbd0cbc2f4c80d7b6422a2879837f82f701ed06dba730360904623a46cceea7b` |
| OMP | PASS; lock `0dbb8c9234546b667860c05cd5a681445f027950d45ba66bb89544839bb90035` |
| Pi | FAIL: `pi-lock-missing-or-stale`, pre-existing recipe/source mismatch; not repaired by changing a fingerprint |
| Manager | PASS: `uv --no-config lock --check --offline`, exit 0 |

No dependency version, archive, or lock was changed. The Task Keeper identity redaction affects only its test fixture; rebuilding its declared archive produced the same source-tree and archive digests as the checked-in lock. The final checks used a temporary HOME and public repository inputs only.

## Results

| Check | Candidate / command | Result |
| --- | --- | --- |
| Baseline full suite | `66ad5e4`; `python -m pytest -q -p no:cacheprovider` | 3602 passed, 1 failed, 9 skipped, 7 subtests passed; obsolete OMP artifact assertion failed |
| Initial narrow fixes | Equivalent tree integrated as `3881ee2`; dependency, OMP foundation, and project-role files | 136 passed |
| Prepared full offline suite | Frozen snapshot above; `python -m pytest -q -p no:cacheprovider --basetemp=<private-temp-root>/pytest` | **3630 passed, 13 skipped, 7 subtests passed**, exit 0, 1415.91 seconds |
| Final malformed package-key guard | `128aeadd`; dependency, DSH upgrade/pipeline, runtime, and extensibility files | **135 passed**, exit 0, 248.71 seconds |
| Final public checker fixture | `8b6df9c`; `python -m pytest -q tests/test_public_docs.py` | **4 passed**, exit 0 |
| ReadSeek environment follow-up | `python -m pytest -q -rs tests/test_pi_cursor_readseek_binding.py` | 1 passed, 4 skipped: system Node unavailable under the isolated PATH; not counted as passed |
| Maintained documentation | `python scripts/check-public-docs.py` | PASS: selected machine-path checks and local file/heading links; final diff whitespace and compilation checks also pass |
| Independent stable-diff review | Implementation boundaries, documentation claims, source/lock/license scope | No critical findings; historical metadata received an additional bounded privacy review |
| Native host / sandbox / live account / other OS / remote CI | No new execution in this cleanup | NOT RUN; historical scope remains in [testing](testing.md) and [known issues](known-issues.md) |

The full suite retained the existing offline guards, fictional credentials, fake subprocess boundaries, and an exclusive `0700` temporary root. Four added skips reflect removal of a hardcoded personal Node fallback; the earlier nine skips remain unpassed scope. A superseded partial run was canceled after new privacy evidence and is not reported as full acceptance. The unrelated TypeScript test-text edit during the completed full run is recorded separately; it did not change the runtime archive and was not executed by pytest.

The completed full log SHA-256 is `236bb8e0b41befea14a656e66cf270c1289ead122b888b114949a0d925e90a3a`. Exact local argv, start/end times, input checksums, status, and sanitized result logs are held in ignored `.cache/release-prep-20261014/` evidence. These local records are not shipped as public raw machine reports.

## Completion and remaining work

| State | Work |
| --- | --- |
| Completed | Narrow lock/OMP fixes; English guides and references; temporary-report consolidation; bounded current-tree privacy cleanup; affected and full offline checks; stable-diff review |
| In progress | None in the documented implementation scope |
| Failed / separate work | Pi lock closure; accepted unresolved Perry safety/audit limitations |
| Environment-dependent / not run | Fresh native hosts, live credentials, other operating systems, and remote CI |

`docs/` was reduced from 1,154 tracked files to 45 maintained Markdown pages. Of the former files, 1,118 were removed; three legacy paths became concise scope summaries because locked plugin/fixture READMEs refer to them. Project specifications were retained, with private-path redaction and explicit notes where raw-report links now point to summaries. Third-party licenses and provenance were retained. A bounded follow-up inspected 91 retained project-record paths for host metadata and stable private paths, with no high-confidence findings in that subset.

This documentation-preparation stage did not rewrite history. A later, separately authorized [local main-only cleanup](history-cleanup.md) removed retired report history and normalized private identifiers and commit metadata. Commit IDs in the earlier evidence above are pre-cutover identities; the private commit map preserves their correspondence. Those results are not relabeled as runs of rewritten commits. The cleanup preserved the complete current file tree, including runtime sources and locks. No deployed agent, account, session, proxy, shell, or terminal configuration was changed. A public release/tag/push is a separate action; this preparation does not claim every integration is release-ready.
