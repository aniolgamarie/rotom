# US3 retirement execution record

Status: repository retirement implemented and targeted checks completed; main-agent final review and feature acceptance remain open.

Only repository sources and explicitly listed distribution artifacts are removed. No user home,
authentication, session, task database, backup, activity record, Git metadata or other worktree is inspected or removed.
The main agent confirmed T035 green and froze both T036 source snapshots before this work began.

## Explicit retired Python modules

- `src/agentcfg/model_delegate.py`
- `src/agentcfg/model_delegate_backends.py`
- `src/agentcfg/model_delegate_batch.py`
- `src/agentcfg/model_delegate_cli.py`
- `src/agentcfg/model_delegate_context.py`
- `src/agentcfg/pi_acceptance.py`
- `src/agentcfg/pi_assets.py`
- `src/agentcfg/pi_auxiliary.py`
- `src/agentcfg/pi_catalog.py`
- `src/agentcfg/pi_checkpoints.py`
- `src/agentcfg/pi_checks.py`
- `src/agentcfg/pi_codex_admission.py`
- `src/agentcfg/pi_cold_rebuild.py`
- `src/agentcfg/pi_cold_sandbox.py`
- `src/agentcfg/pi_commands.py`
- `src/agentcfg/pi_control.py`
- `src/agentcfg/pi_delegate.py`
- `src/agentcfg/pi_delegate_commands.py`
- `src/agentcfg/pi_delegate_files.py`
- `src/agentcfg/pi_delegate_mcp.py`
- `src/agentcfg/pi_delegate_policy.py`
- `src/agentcfg/pi_delegate_spawn.py`
- `src/agentcfg/pi_diagnostics.py`
- `src/agentcfg/pi_editor.py`
- `src/agentcfg/pi_evidence.py`
- `src/agentcfg/pi_extension_bridge.py`
- `src/agentcfg/pi_git_review.py`
- `src/agentcfg/pi_git_status.py`
- `src/agentcfg/pi_guarded_files.py`
- `src/agentcfg/pi_host.py`
- `src/agentcfg/pi_live_project.py`
- `src/agentcfg/pi_login.py`
- `src/agentcfg/pi_mcp.py`
- `src/agentcfg/pi_mcp_script.py`
- `src/agentcfg/pi_mcp_stdio.py`
- `src/agentcfg/pi_native_build.py`
- `src/agentcfg/pi_native_roots.py`
- `src/agentcfg/pi_operations.py`
- `src/agentcfg/pi_output.py`
- `src/agentcfg/pi_pid_namespace.py`
- `src/agentcfg/pi_readseek.py`
- `src/agentcfg/pi_readseek_mutations.py`
- `src/agentcfg/pi_readseek_native.py`
- `src/agentcfg/pi_readseek_prepare.py`
- `src/agentcfg/pi_readseek_results.py`
- `src/agentcfg/pi_readseek_select.py`
- `src/agentcfg/pi_readseek_selection.py`
- `src/agentcfg/pi_readseek_snapshot.py`
- `src/agentcfg/pi_readseek_source.py`
- `src/agentcfg/pi_readseek_vision.py`
- `src/agentcfg/pi_resource_reads.py`
- `src/agentcfg/pi_rules.py`
- `src/agentcfg/pi_scope.py`
- `src/agentcfg/pi_services.py`
- `src/agentcfg/pi_supervisor.py`
- `src/agentcfg/pi_terminal.py`
- `src/agentcfg/pi_upgrade.py`
- `src/agentcfg/pi_validation.py`
- `src/agentcfg/pi_validation_codex.py`
- `src/agentcfg/pi_validation_codex_provider.py`
- `src/agentcfg/pi_validation_delegate.py`
- `src/agentcfg/pi_validation_fixture.py`
- `src/agentcfg/pi_validation_live.py`
- `src/agentcfg/pi_validation_live_delegate.py`
- `src/agentcfg/pi_validation_live_services.py`
- `src/agentcfg/pi_validation_migration.py`
- `src/agentcfg/pi_validation_native.py`
- `src/agentcfg/pi_validation_parent_loss.py`
- `src/agentcfg/pi_validation_provider.py`
- `src/agentcfg/pi_validation_recovery.py`
- `src/agentcfg/pi_validation_report.py`
- `src/agentcfg/pi_validation_runtime.py`
- `src/agentcfg/pi_validation_sandbox.py`
- `src/agentcfg/pi_validation_service_provider.py`
- `src/agentcfg/pi_vendor.py`
- `src/agentcfg/pi_verification.py`
- `src/agentcfg/pi_web.py`
- `src/agentcfg/pi_web_browser.py`
- `src/agentcfg/pi_web_cli.py`
- `src/agentcfg/pi_web_files.py`
- `src/agentcfg/pi_web_git.py`
- `src/agentcfg/pi_web_media.py`
- `src/agentcfg/pi_web_relay.py`
- `src/agentcfg/pi_worker_files.py`
- `src/agentcfg/pi_worker_protocol.py`
- `src/agentcfg/activity.py`
- `src/agentcfg/activity_linux.py`
- `src/agentcfg/activity_macos.py`
- `src/agentcfg/pi_recovery.py`
- `src/agentcfg/process_tracking.py`
- `src/agentcfg/workspace_leases.py`

## Explicit retired scripts

- `scripts/build-pi-vendor.py`
- `scripts/fetch-pi-assets.py`
- `scripts/model-delegate-batch.py`
- `scripts/model-delegate.py`
- `scripts/pi-checkpoint.py`
- `scripts/pi-control.py`
- `scripts/pi-delegate-codex.py`
- `scripts/pi-delegate-mcp.py`
- `scripts/pi-exec.py`
- `scripts/pi-file-operation.py`
- `scripts/pi-namespace-exec.py`
- `scripts/pi-native-recovery.py`
- `scripts/pi-native-scenario.py`
- `scripts/pi-project-check`
- `scripts/pi-readseek.py`
- `scripts/pi-supervisor-macos.c`
- `scripts/pi-supervisor.py`
- `scripts/pi-web-cli.py`
- `scripts/register-pi-evidence.py`
- `scripts/smoke-pi-concurrency.py`
- `scripts/smoke-pi-public-api.mjs`
- `scripts/test-pi-macos-mock.py`
- `scripts/test-pi-mock.mjs`
- `scripts/update-pi-permissions-patch.py`
- `scripts/update-pi-subagents-patch.py`
- `scripts/verify-pi.py`

## Explicit retired dedicated tests

- `tests/test_model_delegate_backends.py`
- `tests/test_model_delegate_batch.py`
- `tests/test_model_delegate_cli.py`
- `tests/test_model_delegate_context.py`
- `tests/test_model_delegate_contract.py`
- `tests/test_model_delegate_lifecycle.py`
- `tests/test_pi_assets.py`
- `tests/test_pi_capability_manifest.py`
- `tests/test_pi_catalog_schema.py`
- `tests/test_pi_checkpoints.py`
- `tests/test_pi_checks.py`
- `tests/test_pi_codex_admission.py`
- `tests/test_pi_codex_endpoint.py`
- `tests/test_pi_cold_rebuild.py`
- `tests/test_pi_cold_sandbox.py`
- `tests/test_pi_commands.py`
- `tests/test_pi_control_routing.py`
- `tests/test_pi_cursor_readseek_binding.py`
- `tests/test_pi_data_assets.py`
- `tests/test_pi_delegate.py`
- `tests/test_pi_delegate_commands.py`
- `tests/test_pi_delegate_files.py`
- `tests/test_pi_delegate_mcp.py`
- `tests/test_pi_delegate_native.py`
- `tests/test_pi_delegate_retirement.py`
- `tests/test_pi_dependencies.py`
- `tests/test_pi_doctor.py`
- `tests/test_pi_editor.py`
- `tests/test_pi_extension_bridge.py`
- `tests/test_pi_git_review.py`
- `tests/test_pi_git_status.py`
- `tests/test_pi_guarded_files.py`
- `tests/test_pi_host.py`
- `tests/test_pi_live_project.py`
- `tests/test_pi_login.py`
- `tests/test_pi_mcp_script.py`
- `tests/test_pi_multirun.py`
- `tests/test_pi_native_build.py`
- `tests/test_pi_native_roots.py`
- `tests/test_pi_operations.py`
- `tests/test_pi_optional_capabilities.py`
- `tests/test_pi_output.py`
- `tests/test_pi_pid_namespace.py`
- `tests/test_pi_readseek_controller.py`
- `tests/test_pi_readseek_driver.py`
- `tests/test_pi_readseek_mutations.py`
- `tests/test_pi_readseek_native.py`
- `tests/test_pi_readseek_prepare.py`
- `tests/test_pi_readseek_results.py`
- `tests/test_pi_readseek_selection.py`
- `tests/test_pi_readseek_snapshot.py`
- `tests/test_pi_readseek_source.py`
- `tests/test_pi_release_gate.py`
- `tests/test_pi_rules.py`
- `tests/test_pi_services.py`
- `tests/test_pi_supervisor.py`
- `tests/test_pi_terminal.py`
- `tests/test_pi_upgrade.py`
- `tests/test_pi_validation_codex_provider.py`
- `tests/test_pi_validation_fixture.py`
- `tests/test_pi_validation_live.py`
- `tests/test_pi_validation_live_delegate.py`
- `tests/test_pi_validation_live_services.py`
- `tests/test_pi_validation_migration.py`
- `tests/test_pi_validation_native.py`
- `tests/test_pi_validation_parent_loss.py`
- `tests/test_pi_validation_provider.py`
- `tests/test_pi_validation_report.py`
- `tests/test_pi_validation_runtime.py`
- `tests/test_pi_validation_sandbox.py`
- `tests/test_pi_validation_service_provider.py`
- `tests/test_pi_vendor.py`
- `tests/test_pi_verification_cli.py`
- `tests/test_pi_web.py`
- `tests/test_pi_web_browser.py`
- `tests/test_pi_web_cli.py`
- `tests/test_pi_web_files.py`
- `tests/test_pi_web_media.py`
- `tests/test_pi_web_relay.py`
- `tests/test_pi_worker_files.py`
- `tests/test_pi_worker_protocol.py`
- `tests/test_register_pi_evidence_negative.py`
- `tests/test_model_delegate_codex_worker.py`
- `tests/test_pi_activity.py`
- `tests/test_pi_activity_linux.py`
- `tests/test_pi_activity_macos.py`
- `tests/test_pi_control_anchor.py`
- `tests/test_pi_control_recovery.py`
- `tests/test_pi_readseek_vision.py`
- `tests/test_pi_recover_cli.py`
- `tests/test_pi_workspace_leases.py`
- `tests/test_pi_adapter.py`
- `tests/test_pi_subagents_patch.py`
- `tests/test_fetch_pi_assets.py`
- `tests/test_pi_cursor_profile.py`
- `tests/test_pi_evidence_schema.py`
- `tests/test_pi_mcp_stdio.py`
- `tests/test_pi_pipeline.py`
- `tests/test_pi_recovery_protocol_surrogate.py`
- `tests/test_pi_resource_discovery.py`
- `tests/test_pi_validation_recovery.py`
- `tests/test_pi_validation_recovery_darwin.py`

## Additional retired resource files

- `agents/pi/build/btw-agentcfg.patch`
- `agents/pi/build/mcp-agentcfg.patch`
- `agents/pi/build/permission-system-patch.json`
- `agents/pi/build/permission-system.patch`
- `agents/pi/build/processes-supervisor.patch`
- `agents/pi/build/readseek-agentcfg.patch`
- `agents/pi/build/recipes.json`
- `agents/pi/build/slopchop-agentcfg.patch`
- `agents/pi/build/smart-compact-agentcfg.patch`
- `agents/pi/build/superpowers-agentcfg.patch`
- `agents/pi/build/web-agentcfg.patch`
- `agents/pi/migration/btw-manifest.json`
- `agents/pi/migration/caller-map.json`
- `agents/pi/migration/capabilities.toml`
- `agents/pi/migration/local-plugins-manifest.json`
- `agents/pi/migration/model-delegate-manifest.json`
- `agents/pi/migration/permission-system-manifest.json`
- `agents/pi/migration/preset-manifest.json`
- `agents/pi/migration/processes-manifest.json`
- `agents/pi/migration/readseek-manifest.json`
- `agents/pi/migration/resource-manifest.json`
- `agents/pi/migration/role-map.json`
- `agents/pi/migration/slopchop-manifest.json`
- `agents/pi/migration/smart-compact-manifest.json`
- `agents/pi/migration/subagents-manifest.json`
- `agents/pi/migration/task-keeper-manifest.json`
- `agents/pi/migration/web-manifest.json`
- `agents/pi/prompts/commit.md`
- `agents/pi/prompts/debug.md`
- `agents/pi/prompts/docs.md`
- `agents/pi/prompts/explain.md`
- `agents/pi/prompts/implement.md`
- `agents/pi/prompts/perf.md`
- `agents/pi/prompts/plan.md`
- `agents/pi/prompts/pr.md`
- `agents/pi/prompts/refactor.md`
- `agents/pi/prompts/review.md`
- `agents/pi/prompts/security.md`
- `agents/pi/prompts/test.md`
- `agents/pi/schemas/acceptance-item.schema.json`
- `agents/pi/schemas/acceptance-scope.schema.json`
- `agents/pi/schemas/catalog.schema.json`
- `agents/pi/schemas/evidence.schema.json`
- `agents/pi/schemas/execution-lease.schema.json`
- `agents/pi/schemas/managed-descriptor.schema.json`
- `agents/pi/schemas/migration-proposal.schema.json`
- `agents/pi/schemas/migration.schema.json`
- `agents/pi/schemas/operation-grant.schema.json`
- `agents/pi/schemas/permission-policy.schema.json`
- `agents/pi/schemas/process-identity.schema.json`
- `agents/pi/schemas/runtime-receipt.schema.json`
- `agents/pi/schemas/stop-recovery-plan.schema.json`
- `agents/pi/schemas/stop-recovery.schema.json`
- `agents/pi/schemas/termination-evidence.schema.json`
- `agents/pi/schemas/validation-run.schema.json`
- `agents/pi/schemas/workspace-write-lease.schema.json`
- `tests/fixtures/pi/fake-host.mjs`
- `tests/fixtures/pi/helper-host-stub.mjs`
- `tests/fixtures/pi/macos/include/libproc.h`
- `tests/fixtures/pi/macos/include/mach/message.h`
- `tests/fixtures/pi/macos/include/sys/sysctl.h`
- `tests/fixtures/pi/macos/include/sys/un.h`
- `tests/fixtures/pi/macos/include/uuid/uuid.h`
- `tests/fixtures/pi/macos/scope-harness.c`
- `tests/fixtures/pi/mcp-elicitation-stub.mjs`
- `tests/fixtures/pi/mock-boundaries.test.mjs`
- `tests/fixtures/pi/mock-entry.mjs`
- `tests/fixtures/pi/mock-guard.mjs`
- `tests/fixtures/pi/tooling/package-lock.json`
- `tests/fixtures/pi/tooling/package.json`
- `tests/fixtures/pi/web-host-stub.mjs`

## Retired distribution directory boundaries

| Directory | Files removed |
| --- | ---: |
| `agents/pi/runtime` | 209 |
| `agents/pi/roles` | 2 |
| `agents/pi/extensions` | 6 |
| `agents/pi/themes` | 11 |
| `agents/pi/packages/btw-vendor` | 16 |
| `agents/pi/packages/colorful-footer` | 4 |
| `agents/pi/packages/loop-guard` | 18 |
| `agents/pi/packages/mcp-vendor` | 114 |
| `agents/pi/packages/model-delegate` | 8 |
| `agents/pi/packages/openai-proxy` | 10 |
| `agents/pi/packages/openspec-resources` | 35 |
| `agents/pi/packages/permission-system-vendor` | 178 |
| `agents/pi/packages/processes-vendor` | 121 |
| `agents/pi/packages/readseek-vendor` | 15 |
| `agents/pi/packages/rules-vendor` | 21 |
| `agents/pi/packages/session-yolo` | 3 |
| `agents/pi/packages/slopchop-vendor` | 16 |
| `agents/pi/packages/smart-compact-vendor` | 173 |
| `agents/pi/packages/subagents-patch` | 2 |
| `agents/pi/packages/subagents-vendor` | 233 |
| `agents/pi/packages/superpowers-vendor` | 56 |
| `agents/pi/packages/task-keeper` | 438 |
| `agents/pi/packages/todo-vendor` | 33 |
| `agents/pi/packages/web-vendor` | 76 |
| `locks/pi/pi-default` | 2 |
| `locks/pi/pi-managed` | 2 |
| `locks/pi/pi-cursor` | 2 |
| `locks/pi/pi-codex` | 2 |
| `locks/pi/vendor` | 23 |
| `shared/skills/model-delegate` | 73 |

## Retained boundaries

- New Pi adapter/backend/inventory/lifecycle/runtime receipt modules, common framework and run ownership remain.
- New Base/Pro lock slices and schema2 manifest remain; the locks/pi root is retained.
- All five active Pi schemas, three active templates and two daily prompts remain.
- agents/pi/build/licenses, agents/pi/licenses, migration/STARTER-LICENSE and migration/source-baseline.json retain legal/source attribution; no executable archive is created.
- examples/pi-services.toml remains main-owned for a later candidate rewrite. New Base/Pro examples remain.
- tests/test_pi_capture.py, test_pi_core_contracts.py, test_pi_recovery.py and test_pi_test_boundaries.py retain applicable public protection coverage.
- DSH/OMP sources, assertions, fixtures and historical Pi classifier data remain.

The 15 fixture paths listed above were consumed only by the retired Pi mock scripts/packages and removed CI job; no surviving operational consumer was found.

## Validation

The main agent owns task markers and acceptance conclusions. No npm, host, JavaScript, live account or network operation was executed by this worker.

The final affected regression used the repository Python with `-B -m pytest`, these exact file arguments:

```text
tests/test_pi_retirement.py tests/test_pi_reboot_configuration.py tests/test_pi_reboot_dependencies.py
tests/test_pi_reboot_runtime.py tests/test_pi_reboot_pipeline.py tests/test_pi_inventory.py
tests/test_pi_migration_flow.py tests/test_pi_capture.py tests/test_pi_core_contracts.py
tests/test_pi_recovery.py tests/test_pi_test_boundaries.py tests/test_config_resolution.py
tests/test_config_schema.py tests/test_config_examples.py tests/test_config_policy.py
tests/test_config_secret_loading.py tests/test_model_defaults.py tests/test_cli.py
tests/test_presentation.py tests/test_cli_presentation.py tests/test_readiness_evidence.py
tests/test_deployment.py tests/test_runtime_preparation_recovery.py tests/test_dependencies.py
tests/test_omp_dependencies.py tests/test_omp_dependencies_foundation.py tests/test_lock_publication.py
tests/test_isolation.py
-k 'not test_deepseek_tf_reuses_url_but_requires_its_independent_key' -q --tb=short -x
```

Result: exit 0, **899 passed, 1 deselected in 481.38s**. The one deselected case was separately
run unchanged after the main agent explicitly rebuilt the OMP lock: **1 passed, exit 0, 3.75s**.
The real-lock assertion was not replaced with a fake. The main agent's new status/collaboration test
files were outside this regression and remain covered by their own evidence.

Full `pytest --collect-only -qq --tb=short` exited 0 after all test migrations. Production AST and
literal dynamic-import checks find zero imports of the 91 retired modules. Operational-source
scans find no retired SDK/control/delegate registration; references in refusal/absence tests remain
intentional. Generic project generation helpers and their DSH protection tests remain, while the
obsolete public Pi project route is absent.

`git diff --check` exited 0. Required notices and source attribution remain in place. A public-doc
check found obsolete draft anchors and two historical script links before the separately assigned
formal documentation cleanup; that check is not recorded as passed here.

### Source and lock identity

Read-only checks before and after retirement accepted the same new Pi lock:
`522bed3a9815e84ad88235956fa0da8bd21625d59c9126af262659a0288396e7`.

| Profile | Current and stored recipe digest |
| --- | --- |
| pi-base | `1c3ca86823c58bd5142341ca9ba356f8902c148593df7f666da9ff0cbfc95ca0` |
| pi-pro | `298c00eb8421b1904f95692e78a0bcc61bb09d67ad4bcfee461775e6285cad35` |

Unselected old-source deletion did not invalidate the new lock. Shared catalog/Skill changes did
invalidate the OMP lock as designed; the main agent handled its explicit same-version source
resolution and published identity `7afccd2beff673e94eb5e2fdc276f0488e2b70d0a8a424d4b795660aaee694af`.
This record does not claim T036/native/account acceptance.

### Failures and resolutions

- The first migration-flow test used shared admission with the default `create=True`; it correctly
  refused initialization under SH. The fixture now uses existing physical SH with `create=False`.
- The first affected set stopped with **51 passed, 1 failed** on the real OMP-lock assertion after
  shared source changes. Explicit main-agent relocking and the unchanged single-case rerun resolved it.
- An intermediate full collection exposed seven remaining old test imports. Explicit retirement
  authorization and migration of the applicable capture/protection tests restored collection.

The production lack of a complete-release observer remains a known limit: manager exit records
unknown and blocks affected maintenance. No timeout, marker deletion or forced process stop was
introduced. Historical native/account/platform evidence is not transferred to the rebuilt combination.
