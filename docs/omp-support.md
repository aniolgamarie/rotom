# OMP support

Current selected host: official OMP `18.8.6`, commit `f068751e2f1dbdbc195977776d47a26db8697495`. Rotom uses a separate permission plugin and does not rebuild a patched host.

| Surface | Evidence boundary |
| --- | --- |
| Python contracts | Synthetic configuration, package/download fixtures, ownership, launch environment, and recovery tests |
| Linux glibc x64 native | Historical official-host startup, resources, local MCP, UI, and permission-plugin fixtures; retain the candidate of each run |
| Authenticated services | Limited historical Cursor and reviewer samples; no general claim for every model, login, usage, or current snapshot |
| Linux glibc arm64 | Assets and selection logic declared; native acceptance NOT RUN |
| macOS x64 / arm64 | Assets and selection logic declared; native acceptance NOT RUN |
| musl, native Windows, other architectures | Outside current supported native asset selection |

A startup DNS attempt blocked by an isolated network namespace is not evidence that the upstream host never attempts networking. Native operation requires its declared platform environment and credentials; default tests do not launch it.

Historical patched-host material is retired and is not the current runtime architecture. Current source migration, validation gaps, and lifecycle limitations are tracked in [known issues](known-issues.md) and the [Roadmap](roadmap.md).

See [OMP](omp.md), [profiles](omp-profiles.md), [dependency maintenance](omp-dependencies.md), [approval diagnostics](omp-approval-diagnostics.md), and [testing](testing.md).
