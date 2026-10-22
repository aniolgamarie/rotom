# DSH default Agent Teams selection — 2026-10-22

The maintainer requested a tested configuration commit and local integration into `main`, with deployment deferred. This changes the public `dsh-default` profile rather than copying a private machine configuration into the repository. This record identifies the accepted candidate before commit; resulting commit and ref checks are retained in private integration evidence.

## Candidate and scope

| Item | Identity / result |
| --- | --- |
| Target main / sole parent | `60facfba1df5509a918e3c8bc9449d9eeb7b8da6` |
| Profile payload SHA-256 | `a0ac05df34253d0574c09bab04350fe76ddaaf5ad04d942c183bb505366e4713` |
| Complete DSH lock | `e4d56f338da80e7854193c17b3cad7fbcc5feaa4fb221efdc091867158da724d`, unchanged |
| Selection | The existing seven `dsh-default` plugins, in order, followed by `agent-teams` |
| Implementation boundary | Public profile, related tests and current documentation only; no adapter, lifecycle, upstream package or dependency change |

The generic DSH adapter baseline still omits Teams. The independent headless SSH profile keeps its own plugin selection. A complete machine-level plugin list can explicitly disable Teams; arrays replace the selection rather than append to it. Existing deployments read the managed deployed selection until a later explicit apply. See the [DSH guide](../dsh.md) for selection and maintenance instructions.

## Official behavior and limits

The unchanged official `0.2.1-rc.2` bundle makes the root session an implicit Lead. Loading it does not automatically create a teammate or start a team model request. It replaces ordinary direct `subagent` / `subagent_fork` delegation with Teams tools, including `spawn_teammate`; the parent model can choose to delegate while handling a task.

There is no enforced user-only creation switch and no `/team create` command. `/team status` reports the loaded bundle and service. Explicit natural-language requests can ask the Lead to create a named teammate, but this is not a technical restriction on other model-chosen delegation. The existing crash, multiwriter, task-release and persistent-audit limitations remain open. Historical native acceptance is recorded in the [ecosystem record](dsh-ecosystem-upgrade-20261021.md); those runs are not counted as new tests for this change.

## Verification

| Check | Observed result |
| --- | --- |
| DSH and configuration regression, 16 files | **501 passed**, exit 0 |
| Runtime preparation, recovery and concurrency, two files | **8 passed**, exit 0 |
| Initial dependencies/runtime/shared-key group | **111 passed, 1 failed**, exit 1; the failure referenced retired `pi-default` |
| Same failing shared-key case on unchanged target main | **1 failed**, exit 1; confirms the existing fixture mismatch |
| Corrected shared-key file | **23 passed**, exit 0; covers current `pi-base` and `pi-pro` with all credential-isolation assertions retained |
| Whole-machine compatibility | All six profiles validated without resolving credentials |
| New default with the existing deployed Teams-OFF selection | Manager launch admission passed and stopped before credential resolution; no host started |
| Lock and protected implementation scope | Lock read passed; `agents/`, `src/` and `locks/` have no changes |
| Public documentation tests | **4 passed**, exit 0 |
| Public content, local links and final whitespace checks | PASS |

The stale shared-key fixture is updated only to enumerate current Pi profiles. It still verifies unchanged machine bytes, shared key resolution across tools/profiles and exclusion of the synthetic secret from rendered artifacts. Other tests in the initial additional group passed; the complete corrected shared-key file was rerun. The original failed commands remain recorded as failures.

Tests used `PYTHONPATH=src`, temporary HOME/DSH/XDG directories, synthetic models and state, and the existing network and host-process guards. Full argv, exit codes, logs and final file fingerprints are retained privately. Public command forms are:

```text
.venv/bin/python -m pytest -q --tb=short -o tmp_path_retention_policy=failed tests/<16 DSH and configuration files> --basetemp <private-system-temporary-root>
.venv/bin/python -m pytest -q --tb=short tests/test_dependencies.py tests/test_runtime.py tests/test_shared_model_keys.py --basetemp <private-system-temporary-root>
.venv/bin/python -m pytest -q --tb=short tests/test_runtime_preparation_recovery.py tests/test_runtime_concurrency.py --basetemp <private-system-temporary-root>
.venv/bin/python -m pytest -q --tb=short tests/test_shared_model_keys.py --basetemp <private-system-temporary-root>
.venv/bin/python -m pytest -q --tb=short tests/test_public_docs.py --basetemp <private-system-temporary-root>
.venv/bin/python scripts/check-public-docs.py
```

Repository-local public Git identity, resolved author/committer identities and absence of environment overrides are checked before commit. The source/configuration delta received an independent scout review. Execution used the configured executor (`gpt-6.1-sol`, medium) and scout (`gpt-6-luna`, high), with the main agent responsible for the fixture decision, machine compatibility, final review and authorized integration.

## Task status and deployment boundary

| State | Scope |
| --- | --- |
| Completed | Public default selection, explicit OFF coverage, current documentation, affected isolated regressions, existing-deployment compatibility and candidate prepared for the authorized local fast-forward |
| In progress | None in implementation or validation |
| Failed / pending decision | None; the reproduced baseline fixture failure has been corrected and rechecked |
| Environment insufficient / unverified | New real-host, account/model, other-platform and Teams crash/multiwriter checks; none are claimed by this configuration change |
| Deferred by maintainer | Production deployment |

The private machine file, deployed generation and deployed Teams selection were unchanged during compatibility verification. This commit does not run sync/apply, terminate a process or publish remote refs. Existing sessions and future launches keep the deployed composition until explicit maintenance applies the new profile.
