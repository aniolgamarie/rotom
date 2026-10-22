# OMP support

Current selected host: official OMP `18.12.6`, commit `45c35e40c46166dc726ccc52f5d27f40f2449f99`. Rotom uses a separate permission plugin and does not rebuild a patched host.

| Surface | Evidence boundary |
| --- | --- |
| Python contracts | Synthetic configuration, package/download fixtures, ownership, launch environment, and recovery tests |
| Current plugin / SDK | 487 independent plugin tests and 12 official wrapper/runner tests in `write` mode; full SDK type-check unverified |
| Linux glibc x64 native | v18.12.6 version/help, isolated RPC configuration load, permission extension registration, and normal exit passed; no tool/reviewer execution |
| Authenticated services | Limited historical Cursor and reviewer samples; no general claim for every model, login, usage, or current snapshot |
| Linux glibc arm64 | Assets and selection logic declared; native acceptance NOT RUN |
| macOS x64 / arm64 | Assets and selection logic declared; native acceptance NOT RUN |
| musl, native Windows, other architectures | Outside current supported native asset selection |

The [v18.12.6 acceptance record](acceptance/omp-18.12.6-20261023.md) binds the four native checks to their candidate, source, lock, and platform. Authenticated services remain unverified for this candidate. Historical v18.8.6 resources, MCP, UI, and approval evidence does not validate these surfaces on v18.12.6.

A startup DNS attempt blocked by an isolated network namespace is not evidence that the upstream host never attempts networking. Native operation requires its declared platform environment and credentials; default tests do not launch it.

Historical patched-host material is retired and is not the current runtime architecture. Current source migration, validation gaps, and lifecycle limitations are tracked in [known issues](known-issues.md) and the [Roadmap](roadmap.md).

See [OMP](omp.md), [profiles](omp-profiles.md), [dependency maintenance](omp-dependencies.md), [approval diagnostics](omp-approval-diagnostics.md), and [testing](testing.md).
