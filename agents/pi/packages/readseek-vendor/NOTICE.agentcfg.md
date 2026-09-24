# agentcfg ReadSeek adaptation

Source: `pi-readseek@0.9.16`, Apache-2.0. Original license, README,
prompts and distribution are retained. `SOURCE.json` records the original npm
integrity and per-file hashes; `agents/pi/build/readseek-agentcfg.patch` records
the changes to the upstream package. The native ReadSeek executable is a
separate dependency with its own license and platform requirements.

The parent extension retains the nine original tool schemas and renderers.
Execution is redirected to an agentcfg controller; it fails explicitly when
that controller is unavailable. `overrideTools` is fixed to an empty list.
Settings come from explicit instance bindings, without global/project discovery.
Filesystem previews run only inside an authorized worker snapshot.

An isolated worker receives its native executable, cache root, settings and
verified session anchors explicitly. It reports anchor events to the parent.
The parent validates the result and computed file hashes, applies allowed file
changes through FilePolicy and a persistent mutation journal, and publishes
anchors only after acceptance. No arbitrary plugin path, shell command or
implicit binary download is an agent-facing parameter.

Every tool entry point awaits the lazy xxhash initializer (`ensureHashInit`)
before use. The upstream package initializes implicitly through whichever of
`readSeek_grep`/`readSeek_write` happens to run first in a shared session
process; agentcfg workers execute a single tool per isolated process, so the
remaining entry points (`edit`, `search`, `refs`, `rename`, `def`, `digest`,
`view`) must initialize explicitly or their LINE:HASH computation fails
closed.

Integration status: in progress. The supervised controller and Git/rg selection
driver are connected and this derived package is declared in all four recipes.
Native executable projection checks the exact 0.9.16 platform package and binary
header, without executing it. The native LGPL-2.1-or-later license is retained
under `agents/pi/build/licenses/readseek` and copied into the installed runtime.
The exact Qwen3-VL model/projector pair is declared as immutable data assets,
downloaded only during explicit sync, verified by size/hash and mounted read-only
at the native cache layout. Model license and revision provenance are retained.
Private document caches and snapshot paths persist within the same session and
policy binding; source timestamps are preserved, and another operation cannot
replace a snapshot while its execution remains active or unverified.
macOS x86_64 source builds and native/live acceptance remain incomplete. These
source changes and isolated tests are not evidence of native ReadSeek or Pi
execution or a finished release.
