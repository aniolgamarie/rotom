# Versions and release scope

Rotom's Python project metadata currently declares `0.1.0`. This checkout is release preparation; a version field alone does not establish a published release or tag. [CHANGELOG.md](../CHANGELOG.md) describes changes awaiting publication.

## Selected integration baseline

| Component | Version / immutable source | Notes |
| --- | --- | --- |
| DSH Core | `0.2.1-rc.2` | Bounded Linux Perry approval fixtures passed; broader Core, account, and platform acceptance pending |
| dsh-TUI | Official npm `0.16.1`, gitHead `73ff99fbed56563bf154d719effd09f9f9725349` | Session-resume, settings-migration and agentcfg CLI native scenarios passed on isolated Linux fixtures |
| Terminal adapter | `rotom-dsh-cursor-terminal@0.1.3` | Public upstream APIs; exact TUI `0.16.1` peer |
| Cursor subscription | `0.6.12`, `936fb5b40b8efb50a5bb2031c81f3c8f553bf7f8` | Main-session Provider through public terminal authentication adapter |
| Perry auto-review | Official `0.13.7`, gitHead `c49f850aeb734f2f1f2f06de6546b22f3dc8f22f` | Current Core selects inline review without tools; deterministic native file/Bash/manual/timeout passed; lifecycle/audit fixes remain unproved |
| Review context / reviewer preset | `rotom-dsh-review-context@0.2.0`, preset `rotom-auto-review` | Independent public activation probe exposed constant context and structured output only; not selected by current Perry |
| Tmux context / Git Worktrees | Official `0.2.1-rc.2` packages | Selected in local TUI; experimental Worktrees follows existing repository gates |
| Agent Teams | Four official `0.2.1-rc.2` packages | Selected by `dsh-default`; explicitly disable through a complete machine plugin override; isolated Linux member/task/restart and TUI/Perry combination passed |
| SSH workspace | Official SSH provider family and headless `0.2.1-rc.2` | Independent read-only-by-default profile; trusted helper and native endpoint acceptance pending |
| SSH subscription authentication | `rotom-dsh-ssh-subscription-auth@0.1.1` | Public Codex/Cursor authentication APIs; own instance credentials; real terminal/account acceptance pending |
| OMP | `18.8.6`, `f068751e2f1dbdbc195977776d47a26db8697495` | Official standalone runtime; independent Rotom permission plugin |
| Pi | `0.84.4` in current manifest | Complete lock rebuilt through the resolver; Linux pi-default evidence is recorded separately. Other profiles, platforms and live services require their own acceptance. |
| Herdr workspace review baseline | `0.9.5`, protocol `22` | Feature 006 public API/source review baseline, not a statement of the current machine deployment or latest upstream version. [Usage and limitations](herdr-workspaces.md) and [isolated evidence](../specs/006-configurable-workspaces/quickstart.md) keep native acceptance and deployment unverified; guarded close and existing-branch Git creation refuse before dispatch. |
| Manager | Python 3.11+; `uv.lock` | Locked environment, loaded directly from `.venv` |

Lock manifests and complete installer lock files under `locks/` are the authoritative dependency records, including resolved sources, integrity, resources, and transitive dependencies. Do not copy a displayed digest into a lock to bypass validation. DSH's tested toolchain is Node `24.14.0` / npm `11.19.1` with frozen pnpm `11.19.0`; other accepted toolchain versions need their own native evidence.

The former `0.15.0` / `e709863019d56897e64495699c3a945cce194d00` source-build archive remains historical evidence and is not a current recipe input. The [ecosystem acceptance record](acceptance/dsh-ecosystem-upgrade-20261021.md) covers the selected official TUI and the current Perry native scenarios.

The [Perry public-integration record](acceptance/dsh-perry-public-integration-20261021.md) separates configuration/source review from native, account, and real-TUI evidence. The historical `0.12.17` acceptance on 2026-10-14 does not validate this candidate or establish fixes for OFF/late approval or persistent verdict auditing.

## Updating and publishing

1. Select an immutable upstream release/source and inspect its actual packaged API, schema, dependency graph, licenses, and known issues.
2. Update declared inputs through the existing explicit `lock` workflow. Review source, full dependency lock, vendor, and runtime identity changes together.
3. Rebuild in isolated directories and rerun affected offline, native, migration, and account layers according to authorization and scope.
4. Freeze the candidate, record remaining limitations, review privacy and links, and obtain explicit publication authorization before creating a release or updating remote refs.

Ordinary `sync` consumes a lock and `run` launches a deployed contract; neither tracks latest. Native self-update commands are unsupported for managed instances where they bypass this workflow. Drift should be diagnosed and repaired using the declared source.

## Recovery boundary

`rollback` restores the previous managed configuration generation and consumes that backup. It does not downgrade software, restore OAuth/session databases, or make a new session format readable by an old host. Keep an old runtime and native state isolated when a downgrade has not been demonstrated safe. See [operations](operations.md).
