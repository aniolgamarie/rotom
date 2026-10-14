# OMP dependency locks and maintenance

OMP uses the unmodified official v18.8.6 standalone, pinned to upstream commit `f068751e2f1dbdbc195977776d47a26db8697495`. The manager does not install system Bun/Node or execute the upstream installer. `omp-kernel` uses the same official runtime with the repository-owned `omp-permission-control` plugin through public extension APIs. See [releases](releases.md), [testing](testing.md), and [approval design](design/approvals.md) for version and evidence boundaries.

The v18.8.6 native Bash integration uses public Settings, `BashTool.approval()`, and same-name `ctx.invokeTool()` delegation. Its production plugin has been type-checked against that SDK. Upstream removed task's per-call `model` parameter in v18.8.2; the recipes use model roles and agent definitions instead.

## Lock contents

`locks/omp/manifest.json` records the immutable source archive, official assets for four platforms, URLs and SHA-256 digests, upstream material digests, local resources, package entries, licenses, compatibility versions, tree identities, and required interpreters. `locks/omp/upstream/` preserves the complete `bun.lock`, provenance, MIT license, third-party notices, and NOTICE.

The upstream Bun lock preserves source dependency resolution. It does not establish reproducible binary builds. Commit archives, tag archives, and release binaries have independent digests. Local resources are checked by bytes and executable bits against the complete lock inventory; adding, deleting, or changing resources or entry points requires a new lock. MCP programs are not implicitly fetched through `npx` or `uvx`.

## Install, deploy, and run

```sh
./agentcfg --local /private/local.toml --profile omp-kernel sync
./agentcfg --local /private/local.toml --profile omp-kernel plan
./agentcfg --local /private/local.toml --profile omp-kernel apply
```

`sync` consumes the existing lock and prepares a runtime in the selected profile's private cache. It does not deploy configuration or start OMP. `apply` deploys configuration and a verified runtime reference. `run` does not install or repair anything and never substitutes a global OMP from PATH.

Only `runtime_variant = "official"` is supported. The former patched runtime, bridge, builder, and variant publication commands are retired. They must not be rebuilt or released; their old results are historical evidence only. The permission sidecar is `permission-control.json`; the official `config.yml` receives only upstream-supported fields. Local tiny-model review remains unavailable because upstream exposes no installed-only inference API; the plugin does not use private workers or download models.

All package files are staged privately and checked for content, executable bits, directory shape, entry points, and receipt identity before activation. Runtime paths are content-addressed as `<cache>/runtimes/<lock-and-platform-identity>`, outside the instance HOME. Preparing a runtime before first `apply` therefore does not pre-create or adopt a native home.

Receipts record platform, lock identity, source/binary digests, installation paths, and resource identities. A local Python MCP binds the prepared manager Python's canonical absolute path, exact version, and executable digest. These are rechecked at launch rather than resolved again through PATH.

A new lock creates a new runtime identity. Existing deployments retain their saved reference until explicit review and `apply`. Shared package leases protect running packages; repair/replacement requires an exclusive lease. Activation journals live in the cache and include directory fsync. A failed activation restores the old directory where possible; the next explicit `sync` handles an interrupted journal. Unverifiable recovery state is preserved for inspection. Instance configuration pending records are a separate transaction recovered by `apply`/`rollback`.

Configuration/lock errors return 2; ownership, active-instance, or recovery conflicts return 4; missing or invalid dependencies/platform assets return 5; filesystem/internal failures return 6. A configuration rollback restores the previous configuration and saved runtime reference. It does not downgrade software or migrate authentication databases. An unverifiable runtime reference prevents the next run with exit 5.

## Updating the lock

```sh
./agentcfg lock --agent omp
```

This is an explicit dependency-resolution change. Review complete upstream materials, all platform sources/digests, local package contents, and licenses before `sync`, `plan`, and `apply`. A host upgrade also requires adapter capability and discovery review; replacing a URL alone is insufficient. Fixed upstream Catppuccin resources retain their upstream provenance and license.

## Download interruption diagnostics

`setup`/`sync` first report the locked version, platform, and asset, then the actual stage:

| Stage | Meaning |
| --- | --- |
| Waiting for download-cache lock | Another sync holds the same digest's lock; this request has not started |
| Checking complete/partial cache | Local bytes are being hashed; a complete cache hit needs no network |
| Attempt N/3: connection/headers | Waiting for response headers; shows restart or resume and retained bytes |
| Attempt N/3: body | Received MiB, total/percentage when known, average speed, and elapsed time |
| Download failure `category=…` | Attempt count, retained progress, and bounded retry delay |
| SHA-256 check / cache publication | Verify the complete body before staging and activating the runtime |

Body progress updates approximately every 1.5 seconds; transitions and completion are immediate. A heartbeat reports time since the last progress update and does not imply advancing bytes. Connection/read timeout is 60 seconds per operation, not a total download deadline. There are at most three attempts for transient timeout/connection failures, HTTP 408/429/5xx, and short reads.

Downloads use content-addressed `.part` files. A valid 206 and `Content-Range` allow safe resume; a 200 response restarts from zero. Complete length and SHA-256 must match before atomic publication. Messages exclude redirect URLs, proxy credentials, private cache paths, and model keys.

1. Check free space, owner, and private-directory permissions. On WSL, prefer the Linux filesystem rather than `/mnt/c`.
2. For `timeout`, `connection`, `http-408`, `http-429`, `http-5xx`, or `short-read`, keep the partial file and retry `sync` with the same local/profile.
3. For `content-range` or `range-reset`, record the category, platform, and network/proxy arrangement. Check intermediaries or the server; do not splice partial files.
4. For `integrity`, `size-limit`, or `cache-write`, inspect the locked asset, storage, and permissions. Do not alter digests, replace locked URLs, or rename `.part` into a completed asset.

Deleting the cache loses resume progress and is usually unnecessary. Runtime downloads and model-service connectivity are independent paths. A model gateway error is not evidence of a standalone download failure. Private provider endpoints must remain compatible with their declared model IDs and protocols.

## Model declarations rejected before launch

`run` compares native `models.yml` with the selected profile's expected provider/model declarations, including source changes not yet deployed. Diagnostic categories are `models-missing`, `models-link`, `models-read-or-parse`, `models-shape`, `models-provider-set`, and `models-provider-fields`. Set differences expose only missing/extra counts; definition differences expose only affected-provider counts, never IDs, values, or file bodies.

Run `plan` with the same machine/profile selectors, resolve drift/conflicts, and then `apply`; use `setup` when a new runtime is also needed. A setup still downloading has not updated the old `models.yml`. Do not overwrite generated native files or bypass discovery checks.

## Platform boundary

Official assets target Linux glibc x64/arm64 and macOS x64/arm64. musl, Windows, and unknown architectures return 5. Asset availability and isolated platform-selection tests do not prove native execution. WSL and each nonlocal architecture require independent evidence; see the [support matrix](omp-support.md) and [testing](testing.md).
