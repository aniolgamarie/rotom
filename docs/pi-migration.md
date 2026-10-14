# Read-only Pi migration inventory

agentcfg implements Pi inventory/proposal generation and configuration/dependency pipelines with four registered profiles. Source integration and historical installation evidence do not establish current final-candidate acceptance. Pi 0.84.4's lock is pre-existing stale; see [testing](testing.md) and [known issues](known-issues.md).

## Generate a proposal

Use a machine configuration that passes manager validation. The target may be a Pi profile; inventory does not require Pi installation or host execution:

```sh
./agentcfg --machine workstation --profile pi-default plan \
  --from-pi-home /absolute/old/pi-home --from-starter /absolute/starter
```

`--from-starter` is optional but cannot be used alone. The command writes `inventory.json` in the valid machine's private cache, reports entry/pending counts and proposal path, and sets `ready_to_deploy=false`. Exit 0 means inventory completed, not migration/authentication success.

## Interpret the inventory

| Field | Meaning |
| --- | --- |
| `source_state`, `source_matches_baseline` | Source presence and observed bytes compared with frozen Git objects |
| `selected` | Explicit package/theme selection; null for indeterminate automatic discovery, without inferring unselected/loaded |
| `disk_state` | Resource presence, without inferring actual loading or usability |
| `load_evidence`, `execution_evidence` | `not-run`; no host is executed |
| `disposition` | keep/adapt/merge/replace/optional/exclude, with target and reason |
| `blockers` | Source drift, old manager, unknown package refs/filters, unsupported model fields, duplicate models, or missing credentials |
| `private_locations` | Original locations retained only in the private proposal; do not publish the entire file |

Only representable provider/model fields are projected. Literal apiKey values and commands are neither copied nor executed; the proposal requests separately supplied secret references. Unsupported fields remain explicit mapping work rather than becoming defaults. Supported theme selections may produce nonsecret Pi overrides. The proposal is neither a complete local file nor deployable native JSON.

Inventory does not read authentication/trust/session bodies, start Pi/DSH/Codex, access networks, execute old generators, modify old homes/source trees, or copy runtime caches. Unknown resources are `unmanaged-preserved`. Links, unsafe targets, and invalid formats fail explicitly. Original model/service details remain in the private nonsecret proposal.

`agents/pi/migration/role-map.json` maps the seven previous Codex purposes to model_delegate presets. Old codex-delegate/codex-agents are replacement sources, never final execution dependencies.

## Adopt a new instance

1. Keep the private proposal and inspect each blocker/private location. `.starter-sync-manifest.json` is only an old-manager hint; no ownership or Lua synchronizer is inherited.
2. Express required providers/models, themes, and resources in private `local.toml`. Domain skills/derived packages use unique repository sources. Preserve unknown custom files in their old location until explicitly registered. Do not copy authentication, trust, sessions, task databases, or complete models.json into public sources.
3. Choose a new isolated Pi instance root, not the old Pi home. Existing unmanaged native files cause ownership conflicts. Stop old editor/source synchronization from targeting the new instance. Switching does not delete the old environment.
4. Review `validate` → `plan` → `apply`; use explicit `lock`/`sync` when dependencies need preparation. Source inspection is not proof of deployability without valid sources, lock, and platform prerequisites. Apply does not execute a model or transfer login; log in separately inside the final instance.

## Drift, rotation, and rollback

A one-sided native UI change is preserved as drift without becoming a new baseline. Conflicting changes to the same managed field return 4. `capture` extracts only a selected theme and uniquely reversible main model into private `proposals/capture.json`. Full configuration/render validation runs again; the machine file is not changed automatically. Unknown models or ambiguous mappings are not added.

Secrets resolve at run through environment injection. Managed models.json apiKey fields must remain declared `$AGENTCFG_PI_CREDENTIAL_*` references. A literal native secret blocks plan/apply/capture rather than becoming capturable drift.

Multi-file deployment writes pending recovery state first. Failures restore the old configuration where safe; unprovable recovery retains pending and returns 4. Invalid credentials or missing protection declarations in current/previous/pending records are rejected, never silently repaired. No-op apply reports `changes=0` without rotating previous. Successful rollback consumes the single previous backup and preserves authentication, sessions, Task Keeper databases, runtime-created files, and user keybindings. Rollback restores configuration/saved runtime references, not software versions or databases.

## Active leases and explicit recovery

Pi apply/sync/rollback share instance admission. Exited parent Pi with active worker/check/Codex/external or unknown leases still blocks writes with 4. Changing HOME/state root cannot bypass instance ownership or cross-instance worktree write leases.

```sh
./agentcfg --local /private/local.toml --profile pi-managed recover pi --lease LEASE_ID
./agentcfg --local /private/local.toml --profile pi-managed recover pi --lease LEASE_ID --stop --expect-plan PLAN_DIGEST
```

The first command verifies and generates a stop plan valid for 300 seconds; the second explicitly authorizes stopping. Generation revocation and controlled termination require proof that the old controller is gone and target identity matches. Unknown identities, reused PIDs, external activity, and expired plans retain protection. Recovery does not revive execution authority. After proven termination, Task Keeper user resume creates a fresh attempt for the same task with the original candidate/budget.
