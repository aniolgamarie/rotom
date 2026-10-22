# OMP 18.12.6 candidate acceptance — 2026-10-23

This record covers the unmodified official standalone runtime and the repository-owned plugin compatibility update in candidate `9be0d6fd1248119ed2ed999b21f32b4db6955ab3`, based on `39a9389d3bddc27f394fa26bc75236cf1bb0b89c`. It records explicitly authorized isolated native smoke, offline tests, and their limits. It does not record production deployment or integration into main.

## Fixed inputs

| Input | Identity |
| --- | --- |
| Official release | [v18.12.6](https://github.com/can1357/oh-my-pi/releases/tag/v18.12.6) |
| Official source commit | `45c35e40c46166dc726ccc52f5d27f40f2449f99`, verified from the official tag reference |
| Source archive SHA256 | `645df2d527de1b0ff62514ac14250230622439d5d5e84f781ffa06d38415b8d0` |
| Complete OMP lock identity | `d07a31bdf0d8d56549160871f18b691a30243ab86cdc4d6ca6003d697e89df1a` |
| Exercised platform | Linux glibc x64 |
| Official Linux x64 asset | `omp-linux-x64`, 256702432 bytes |
| Binary SHA256 | `85d9daf3a05fc76e8cd425ae1904eb576af8d21cc85fcf4690742626e07ccfa4` |
| Native smoke runner SHA256 | `c0253e71d0b52df3bd3e5b8662984e6fae95d28b479bf79fe90956535f63786d` |

The explicit resolver regenerated the complete lock, upstream Bun lock, provenance, license, and notices from the verified source archive and official asset digests. Only the current platform binary was downloaded. `OmpBackend.sync` assembled and verified a separate staging package with status `installed`; staging blocked subprocess creation and secret loading/resolution, with neither attempted. No host or upstream source was patched.

## Repository-owned plugins

| Plugin | Change and evidence |
| --- | --- |
| `rotom-health` | Compatibility declaration updated to v18.12.6; production code unchanged; no new native plugin smoke |
| `echo-mcp` | Compatibility declaration updated to v18.12.6; production code unchanged; no new native MCP smoke |
| `omp-permission-control` | Compatibility/package source identity updated to v18.12.6; production code unchanged; offline suites and the native registration check below |

## Offline acceptance

- The current independent permission plugin suites passed 487 Bun tests using fake host/model/native boundaries. These do not establish real SDK or service execution.
- Twelve separate tests passed with the pinned official SDK's real wrapper, runner, approval, cache, and related modules. Their source closure hashes are fixed in the fixture. They cover the selected `write` approval mode, native/user deny and prompt preservation, tool-call replacement/blocking, delegation, cancellation, and worktree helpers. External I/O boundaries fail immediately if reached; approval resolution and grant conclusions are not replaced with fabricated results. This does not accept `always-ask-cached` or provide full SDK type-check evidence.
- The seven-file Python command covering dependency/foundation, adapter, pipeline, execution/source, and backend contracts initially returned 177 passed and one failed in the trusted UID view. The failure was an adapter fixture's hardcoded old compatibility version. After binding it to the current `TAG`, the complete adapter file plus public-document checks returned 28 passed, exit 0. The corrected failure is therefore rechecked; the earlier failing run is retained as failing evidence.
- A preceding sandbox UID view caused path-ancestor ownership failures; the trusted-view rerun resolved that environment mismatch without changing safety checks.
- Stable diff whitespace and added-line public-content checks passed. Raw logs remain private; this public record contains portable command paths and synthetic fixtures only.

## Authorized native checks

All four host processes used a fresh temporary HOME, XDG roots, agent directory, and working directory. The child environment was explicit; it contained no account credentials or inherited secret variables. Linux seccomp denied network socket creation through `deny_network`. Both RPC fixtures selected a fictional `fixture/offline-fixture` model at `https://example.invalid/v1` with the official `auth: none` setting. No prompt, tool call, or reviewer request was sent.

The following are the actual argument vectors with only runtime and temporary paths normalized. `<runtime>` denotes the verified staging package; `<tmp>` denotes the fresh isolated test root. The RPC processes received exactly `{"id":"fixture-state","type":"get_state"}` followed by a newline and stdin EOF.

```text
<runtime>/bin/omp --version
<runtime>/bin/omp --help
<runtime>/bin/omp --model fixture/offline-fixture --mode rpc --no-ui --no-session --no-extensions --no-skills --no-rules --no-tools --no-lsp --no-pty --no-prewalk
<runtime>/bin/omp --model fixture/offline-fixture --mode rpc --no-ui --no-session --no-extensions --no-skills --no-rules --no-lsp --no-pty --no-prewalk --extension <runtime>/packages/omp-permission-control/standalone.ts
```

| Check | Exit | Observed result |
| --- | --- | --- |
| Version | 0 | `omp/18.12.6` |
| Help | 0 | Usage and flags printed normally |
| Bare RPC | 0 | `PI_CODING_AGENT_DIR=<tmp>/agent`; `autoCompactionEnabled=false` demonstrated temporary configuration loading; fictional model selected; `messageCount=0`; normal exit after EOF |
| Permission extension RPC | 0 | `PI_CODING_AGENT_DIR=<tmp>/kernel-agent`; valid synthetic permission sidecar with `nativeBash=true`; `permission_bash` and the repository's native Bash wrapper appeared in `get_state.dumpTools`; configuration loaded; `messageCount=0`; normal exit after EOF |

`--no-extensions` disables ambient discovery while the official CLI still loads the explicitly supplied `--extension`. The bare RPC check alone does not validate permission plugin loading. The fourth check validates registration and initial sidecar loading, not permission decisions or reviewer execution. Both RPC stderr streams were empty. All four subprocesses exited; no matching staged OMP process remained after the run.

The temporary runner first needed its help-output expectation and newline encoding corrected. A subsequent RPC attempt without a selected model exited with “No default model selected”; adding the public keyless fictional model supplied the missing fixture prerequisite. These were test-tool corrections, not host patches or hidden passes. The final four checks all returned zero.

## Remaining evidence boundaries

| State | Scope |
| --- | --- |
| Completed | Source/asset/lock verification; isolated package preparation; offline checks above; four Linux x64 native startup/configuration/registration/exit checks |
| In progress | No remaining work in this acceptance package |
| Failed pending decision | None after the documented fixture corrections and reruns |
| Environment insufficient / unverified | Full type-check against the new SDK: compiler/dependency closure unavailable |
| Not exercised | Linux arm64 and macOS native operation; real accounts/login and model services; approval/reviewer execution; tool execution; PTY/LSP/MCP/UI behavior; native smoke of `rotom-health` or `echo-mcp`; `always-ask-cached`; production deployment and migration |

Historical v18.8.6 native/account/approval results do not establish those untested surfaces on this candidate. The four startup checks do not imply that every tool, plugin, service, or platform is accepted.
