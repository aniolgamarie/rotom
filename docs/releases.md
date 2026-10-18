# Versions and release scope

Rotom's Python project metadata currently declares `0.1.0`. This checkout is release preparation; a version field alone does not establish a published release or tag. [CHANGELOG.md](../CHANGELOG.md) describes changes awaiting publication.

## Selected integration baseline

| Component | Version / immutable source | Notes |
| --- | --- | --- |
| DSH Core | `0.2.1-rc.2` | Selected upgrade candidate; native/account/platform acceptance pending |
| dsh-TUI | `0.15.0` source build, `e709863019d56897e64495699c3a945cce194d00` | Unmodified upstream main source and fixed submodule; upstream build/publish flow, archived by integrity |
| Cursor subscription | `0.6.12`, `936fb5b40b8efb50a5bb2031c81f3c8f553bf7f8` | Main-session Provider through public terminal authentication adapter |
| Perry auto-review | `0.12.17`, `2b931b8375f9ee9ebe20e80ef336c69804e1aac0` | Enabled; unresolved limitations explicitly retained |
| Tmux context / Git Worktrees | Official `0.2.1-rc.2` packages | Selected in local TUI; experimental Worktrees follows existing repository gates |
| SSH workspace | Official SSH provider family and headless `0.2.1-rc.2` | Independent read-only-by-default profile; trusted helper and native endpoint acceptance pending |
| OMP | `18.8.6`, `f068751e2f1dbdbc195977776d47a26db8697495` | Official standalone runtime; independent Rotom permission plugin |
| Pi | `0.84.4` in current manifest | Complete lock rebuilt through the resolver; Linux pi-default evidence is recorded separately. Other profiles, platforms and live services require their own acceptance. |
| Manager | Python 3.11+; `uv.lock` | Locked environment, loaded directly from `.venv` |

Lock manifests and complete installer lock files under `locks/` are the authoritative dependency records, including resolved sources, integrity, resources, and transitive dependencies. Do not copy a displayed digest into a lock to bypass validation. DSH's tested toolchain is Node `24.14.0` / npm `11.19.1` with frozen pnpm `11.19.0`; other accepted toolchain versions need their own native evidence.

## Updating and publishing

1. Select an immutable upstream release/source and inspect its actual packaged API, schema, dependency graph, licenses, and known issues.
2. Update declared inputs through the existing explicit `lock` workflow. Review source, full dependency lock, vendor, and runtime identity changes together.
3. Rebuild in isolated directories and rerun affected offline, native, migration, and account layers according to authorization and scope.
4. Freeze the candidate, record remaining limitations, review privacy and links, and obtain explicit publication authorization before creating a release or updating remote refs.

Ordinary `sync` consumes a lock and `run` launches a deployed contract; neither tracks latest. Native self-update commands are unsupported for managed instances where they bypass this workflow. Drift should be diagnosed and repaired using the declared source.

## Recovery boundary

`rollback` restores the previous managed configuration generation and consumes that backup. It does not downgrade software, restore OAuth/session databases, or make a new session format readable by an old host. Keep an old runtime and native state isolated when a downgrade has not been demonstrated safe. See [operations](operations.md).
