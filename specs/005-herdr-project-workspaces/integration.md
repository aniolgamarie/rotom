# Main integration record — 2026-10-20

The integration combines the completed Herdr feature with the current Pi Base/Pro implementation. It authorizes local source integration only; production configuration, binary selection and the user's default SSH entry remain explicit operations described in the [usage guide](../../docs/herdr-workspaces.md).

## Candidate and ownership

- Target main: `b18da6d1df885a81400d721cb46eafdd5c34bb1e`.
- Feature commit: `2d808adc6c5040feca4cf9d323debcd970e800dd`; its parent and the common ancestor are `93e4f7899725336c1180e53b4ec239eea5f984ce`.
- The feature introduces one commit beyond that common ancestor. Both newer main commits are retained. No old lineage is replayed across a history cutover.
- Integration uses a separate worktree. The original checkout's other branch and staged work are preserved; no remote update or worktree retirement is part of this operation.
- Final source inventory: 386 files covering entrypoints, Python source, schemas, terminal configuration, tests, benchmark tools and manager dependency declarations. Its canonical JSON SHA256 is `2355b154b49bd7ce6ae47c0002168d10575d43a9efa4518c9ec85e06bf1dcb5c`. The prepared commit and tree bind the complete final content, including documentation, in the private integration receipt.

## Integration decisions

1. Retain main's Pi manifest and Base/Pro lock layout. Do not restore the four retired Pi lock directories. All locks, profiles and `agents/pi` resources remain byte-for-byte unchanged from the target main. Pi manifest SHA256: `7a9b6c9ecff517611678a6ca5770e3df1b1fa8a66f5ce29f719276d795f6b5ff`.
2. Port only the accepted `inventory()` path/content checks into main's Pi runtime-package module. Retain main's installation validation, sealing and status implementations. Keep the main migration inventory tests and add the runtime inventory tests as a separate file.
3. Use the adapter's existing public `validate_runtime_binding()` during work preflight, after environment validation and before runtime inspection, pending metadata or tab creation. Reject stale bindings through the existing redacted conflict path. Do not duplicate the Pi binding algorithm or modify an upstream host.
4. Preserve constitution principle IX on community selection. Add compatibility and upgrade governance as principle X, producing constitution 2.3.0, and update the feature's principle references. Record the original ratification date as unrecorded historical metadata; do not invent a date or substitute this amendment date for it.
5. Update current examples to `pi-base` / `pi-pro` and use an absolute repository entrypoint with a consistent machine selector. Document PATH preparation for static doctor, explicit configuration deployment, reconnecting, editor keys and rollback.

## Verification

Tests ran on the sole available Linux environment with the prepared Python 3.11 environment. Host-view execution used a minimal child environment with independent temporary HOME, DSH/Pi/Codex, all XDG and TMPDIR paths before pytest started. Per-test offline guards remained enabled; these checks did not launch third-party agent hosts or use real accounts.

| Check | Observed result |
| --- | --- |
| Affected Herdr/termcfg/Pi inventory and shared configuration/deployment/runtime contracts, 62 test files | 1,550 passed; 8 failures identified obsolete Pi fixtures in the two files below; raw exit 1 retained |
| Corrected `test_execution_environment_runtime.py` and `test_local_values.py` | 47 passed, 9.19 seconds, exit 0; current Pi reserved-variable policy and Base/Pro URL resolution covered |
| Work preflight plus roles/launch/recovery/context | 79 passed, 0.77 seconds, exit 0; missing/stale adapter bindings fail before runtime, pending, tab or secret access |
| Stable source, lock and ancestry review by an independent scout | Passed within the integration decisions above |
| Whitespace and public documentation/link checks | Exit 0; no findings |

The affected run's eight failures are resolved by the corrected-file run. Between those runs, only the two test files changed in the frozen source inventory; runtime source and all remaining tested files stayed unchanged. The first preflight regression run was also retained as RED before the fix. There are no unresolved failures in this integration gate.

The affected command was `.venv/bin/python -m pytest -q -p no:cacheprovider --basetemp <temporary-HOME>/q` followed by the 62 selected repository test paths. The selection covers all `test_herdr_*`, `test_work_*` except independently checked `test_work_tools.py`, `test_termcfg*`, `test_pi_reboot*`, `test_config*`, `test_execution_environment*`, plus Pi inventories, local values, deployment, runtime/concurrency/preparation recovery and OMP execution-environment contracts. The path above is a normalized description; exact argv, selected paths, exit codes and raw output remain in private receipts.

Evidence SHA256:

- Affected-run receipt: `7604efa86d63ba536b18086f52140910eba318b9b8d8d33668529a0f94b3da5d`.
- Affected-run raw output: `ca5ffdf2a5f1086ef5491913c53787211057cf3f97d9627e7701f1f0c7083e56`.
- Corrected Pi fixtures: `3d75fbfef8f139f50e7c1ca158cc7d015f797996e594ddb9f37258a257a7dd9d`.
- Work preflight GREEN: `67c7378d594db35817d7bf1056ded515f61c002e2d7eef19f840ca693cbc8dd6`.
- Work preflight RED: `9642f6cc1ce2fe848d43dd68abf3b35fc1739f0d737efee9474831316ef0ee16`.

A broader run was stopped by an explicit scope decision after 711 passes, exit 2; it is not a full-suite pass. Earlier attempts affected by exhausted temporary storage or repository-local private-state restrictions are retained as environment failures. The final checks used temporary HOME storage on a separate filesystem, without changing runtime path protections. Only the verified temporary tree of the interrupted storage-failure run was removed.

The bounded public-content checker is separately identified by SHA256 `7c6a572dea0a91d6afd1b984e47f224bbdf7dfe5698af8fd2c192d9a6288530e`; its findings, exclusions, history check, and the final read-only specification analysis are saved with the final commit receipt. These checks do not establish comprehensive historical credential absence.

## Acceptance boundaries

The original 66 feature tasks and [accepted first baseline/canary summary](acceptance-summary.json) retain their frozen source, asset, configuration, rule and evidence identities. The 20,370-second baseline is not relabeled as a new integrated-main measurement. This integration does not require another full-duration baseline merely because Git history is combined.

Current Pi Base/Pro native sessions, accounts and model calls are not qualified by the old Pi native receipts or by these offline checks. Agent status extensions remain disabled. Native-state downgrade compatibility remains unproven, retaining the `compatibility_unproven_stop` branch. Production activation and other client/server platforms remain separate from this local integration.
