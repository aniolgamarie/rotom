# Pi ReadSeek integration

The derived ReadSeek sources, supervised controller, and fixed vision assets are declared for all four Pi profiles. Source/mock integration does not establish current Pi or ReadSeek native acceptance. The current Pi 0.84.4 lock is pre-existing stale; historical candidate results are recorded in [testing](testing.md).

## Execution contract

The parent session preserves the nine tools' arguments, descriptions, and result rendering while routing execution through agentcfg. A missing controller fails explicitly without falling back to raw file IO. `overrideTools` stays empty: ordinary tools and Task Keeper `tk_*` tools are not replaced.

Workers receive only fixed tool names, explicit arguments, private file copies, cache directories, and native executable paths. They load tool definitions through a fake Pi registration interface rather than a second Pi session. Copies include only FilePolicy-readable files; original project directories, Git metadata, global accounts, and settings are not implicit worker inputs.

Artifacts bind invocation ID, copy digest, tool name, and actual file inventory/content digests. The parent rereads/verifies artifacts instead of trusting success text. Read-only calls and rename previews must not modify files. Ordinary write/edit can change only requested files; cross-file symbol rename requires a complete authorized scope. Unexpected deletion, additional files, and links are rejected.

All targets pass permission/baseline checks before per-file compare-and-swap writes with persistent journals. Revocation or mid-operation failure does not automatically retry, roll back, or report whole-operation success. Session anchors bind content digests and are not reused after copy changes. They update only after accepted results and physical termination proof.

Selection and computation share one execution lease. The first-party driver makes fixed read-only Git/rg queries, requests exported files from the supervisor, and enters a copy-only computation sandbox. Third-party processes never receive supervisor RPC credentials. No second manager/queue is introduced. ReadSeek and MCP share `supervised-stdio` transport but retain separate bindings/protocols; Codex remains on official CLI/native tools.

A worker `ready` means computation artifacts are available. Verification, controlled commit, acknowledgment, physical exit, and session publication follow in that order. Large results return in digest-checked chunks. Stable private copy/cache paths preserve source mtimes within one session/permission contract. Previous copies are cleaned only after termination; cache remains, and out-of-bounds links are not followed. Permission/instance changes select a new cache namespace.

## File selection

Git selection preserves tracked and nonignored untracked defaults, plus explicit cached/others/ignored categories with NUL-delimited inventories. The worker Git adapter answers only exported fixed `ls-files` queries, not arbitrary Git commands. Tracked files in `target/` or `node_modules/` must not disappear through a replacement directory walk. Without Git, upstream traversal skips `.git`, `.readseek`, `target`, and `node_modules`.

Control characters, backslashes, and invalid UTF-8 filenames fail at the existing agentcfg path boundary. A subdirectory session's workspace rename stays within its original cwd scope. Read-only searches mark permission-excluded scope incomplete; cross-file writes reject incomplete scope. grep first selects using original-project ignore rules, then runs the explicit rg binding on copies. It does not discover global rg/configuration or trigger SDK downloads.

Before native computation, mapping validates that private-copy path prefixes occur in neither original file contents nor user input, preventing accidental replacement of literal source text.

## Bindings and limits

```toml
[overrides.profiles.pi-default.agent_options.readseek]
node_tool_ref = "readseek-node"
git_tool_ref = "readseek-git"
rg_tool_ref = "readseek-rg"
max_seconds = 300

[overrides.profiles.pi-default.agent_options.readseek.settings]
syntaxValidation = "warn"
imageMode = "auto"
timeoutMs = 300000

[overrides.profiles.pi-default.agent_options.readseek.settings.display]
edit = "expanded"
write = "expanded"
grep = "compact"
```

Each reference must name an `external_tools` binding and have a `bash`/`execute` allow rule for `tool:REFERENCE`. Bind Node's locked version. Git/rg must be noninteractive, read-only, project-bound, and free of extra arguments. Command permission does not substitute for FilePolicy or worktree write leases.

Read-only files are limited to 16 MiB and writes to 1 MiB, matching ordinary tools. One copy is limited to 10,000 files/128 MiB; results to 32 MiB. Exceeding limits fails. Missing Node/Git/rg bindings report missing configuration without global fallback.

## Platform builds and assets

ReadSeek 0.9.16 has no upstream macOS x86_64 prebuilt package. Explicit `sync` uses the declared local source build, requiring Git, Zig **0.16.0**, make, Python 3, patch, and Xcode SDK. `agents/pi/build/readseek-source.json` pins ReadSeek, SQLite, zig-clap, zigimg, and PDFium commits. Build-script/upstream PDFium-lock digests are checked; download/build occurs in a separate temporary HOME, and Zig dependencies use source content hashes. The receipt preserves Mach-O x86_64 digest, SDK version, and static dependency licenses. Failure does not activate a package. This path has substitute-test coverage, not an Intel Mac build pass. Linux architectures and macOS arm64 use fixed platform packages.

The two fixed vision assets total 1,552,463,168 bytes and historically passed download-size, SHA-256, and GGUF checks. That did not execute inference or establish image/PDF understanding. PDF/image/vision, cache continuity, and all nine tools require native evidence for the final identity.

Historical intermediate four-profile installation/sealing and isolated regressions cannot be inherited after source changes. Tool-registration-only checks did not call tools, start hosts, access the network, or run native programs. Current native/cold gaps and platform scope are tracked in [testing](testing.md), [known issues](known-issues.md), and [roadmap](roadmap.md).
