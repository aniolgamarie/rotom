# Herdr upgrade evidence

Use an unmodified official release. Before an installation or upgrade, explicitly
check the latest stable release on the [official release page](https://github.com/herdrdev/herdr/releases/latest).
Record the selected release/tag/commit, exact asset URL and SHA256, disk client and
running server versions, configuration/rules/integration digests, source/target-main
commits and dependency-lock digest. If retaining an older release, record the reason
and a concrete reevaluation trigger. Version strings alone do not establish protocol
or capability compatibility. This document does not record a completed native run.

The runner uses the prepared repository Python environment, never installs tools,
reads credentials, changes locks, patches Herdr or changes the production default.
The checked-in fixtures are synthetic examples with deliberately missing budgets,
calibration and authorization. Their fictitious commit and asset hashes are not
release receipts. They validate offline and cannot produce performance PASS.

```sh
.venv/bin/python tools/bench/herdr_upgrade.py validate \
  --manifest tests/fixtures/herdr-bench/v1/manifest.json \
  --policy tests/fixtures/herdr-bench/v1/policy.json
```

Manifest paths resolve relative to the manifest file. CLI paths resolve relative
to the caller's cwd. Unknown fields, duplicate JSON keys, nonfinite numbers,
incorrect canonical digests, unit/scope mismatches and altered fixture identities
fail validation. Self digests exclude only the document's `digest` field and use
sorted-key UTF-8 compact JSON without ASCII escaping. External files use their
original byte digest. Structural validity is separate from native acceptance.

## Establishing the first baseline

The acceptance owner approved the following sole-host budgets on 2026-10-19,
before new candidate CPU performance windows. They are usability and resource
limits, not values inferred from candidate CPU results. A separately frozen native
policy records that approval; the checked-in synthetic policy remains unapproved.
A/A calibration still produces a distinct policy requiring review and approval.

| Required metric | Approved absolute limit | Acceptance purpose |
| --- | --- | --- |
| Warm enter/reuse p95 | 1000 ms each | Routine project navigation completes within one second |
| New ordinary role p95 | 3000 ms | A prepared ordinary terminal opens within three seconds |
| Cold server readiness median | 5000 ms | Explicit cold entry completes within five seconds |
| Attach-to-fixed-input p95 | 3000 ms | Reconnection becomes usable within three seconds |
| Server plus helpers CPU | 1 core average / 300 core-seconds per 300-second window | Bound multiplexer cost separately from clients and producers |
| Server plus helpers RSS median / p95 / peak | 384 / 448 / 512 MiB | Bound retained and peak multiplexer memory |
| Settled RSS growth slope | 1024 bytes/second | Limit growth across the six settled checkpoints plus the 30-minute tail endpoint |
| Registered terminal objects | 30 | Match the largest fixed retained workload |
| Sampled processes / file descriptors | 96 / 4096 | Bound the complete sampled test process set |

Later A/B regressions must exceed both 10% and the metric's absolute allowance:
50 ms for latency, 3 core-seconds or 0.01 core for CPU, 8 MiB for RSS,
128 bytes/second for slope, one object, four processes or 32 descriptors.
The near-zero denominator is 1 ms, 0.3 core-seconds / 0.001 core, 1 MiB,
64 bytes/second, or one count respectively. Optional PSS/wakeup retain
null budgets and explicit missing-evidence reasons. A/A derives a separate noise
envelope; it cannot increase these absolute limits or erase an initial failure.

Approval must precede new candidate performance windows. Calibration and first
baseline each retain the complete three-batch matrix, at least 5h08m12s of fixed
workload windows per subject, excluding setup and operation samples. Together
they require at least 10h16m24s on the sole server. A smaller diagnostic remains
partial and cannot replace that baseline.

1. Freeze the fixture, measurement method, environment category, absolute budgets,
   regression thresholds, near-zero rule and full three-batch retest method before
   observing candidate performance. Record the approval and frozen policy digest.
2. Obtain explicit native benchmark authorization. A command-line reference is an
   audit label; it does not grant authorization. Prepare a new private isolation
   root and an outside-repository 0700 directory for 0600 execution originals.
   Select one supported isolation route: a verified loopback-only network
   namespace, or the explicit `--offline-sockets` policy described below. With
   `--isolated-netns`, the fixed helper creates an unprivileged user/network
   namespace, maps only the existing UID/GID to themselves and reexecutes this
   runner. It does not request host privileges or modify host networking. A
   denied namespace or any interface other than loopback fails closed for that
   route. The mutually exclusive offline-socket route must pass its actual
   seccomp/socket/descriptor proofs; it is not a network namespace, and the
   runner never silently falls back between routes.
3. Use `calibrate` for same-candidate A/A replay when no accepted baseline exists.
   It derives per-metric three-batch range envelopes and preserves absolute budgets.
   Output policy has no approval or freeze timestamp. Review its native coverage and
   originals before approving a separately named, frozen policy. Invalid calibration
   or incomplete required coverage cannot become performance acceptance.
4. Run and compare `first-baseline` with subject `candidate` and no baseline report.
   A scoped pass is a first baseline, never an A/B upgrade-regression result.
   When reusing the frozen manifest after calibration, first confirm that the
   calibration and every owned process have exited and all four delegated groups
   are empty using fresh membership reads. Preserve the complete owned isolation
   tree in a new private archive on the same filesystem, without overwriting any
   destination, so the original isolation path is absent. Keep the manifest and
   its directory, records, sentinels and recorded argv unchanged; verify calibration
   originals again before running. The runner creates a fresh tree at that same
   frozen path. Reusing the old tree fails preflight, while changing only the root
   can break normalization of the calibration's saved argv. Existing records may
   remain in their private directory; every new report/output must use a new name.
   This archive step is a conditional procedure, not evidence that a run passed.
5. Later, freeze separate manifests for `runtime` and `full-stack`. Runtime must
   hold configuration, detection rules, integration, fixture, tool and environment
   identity fixed; full-stack records each actual input identity. Require an accepted
   baseline, same-machine A/B reports, approved same-baseline A/A calibration and all
   three batches. Keep the first run when retesting; do not select the best batch.

```sh
.venv/bin/python tools/bench/herdr_upgrade.py calibrate --manifest bench/manifest.json \
  --policy bench/absolute-policy.json --subject candidate --allow-native \
  --authorization native-bench-approval-01 --output bench/aa.json \
  --policy-output bench/policy-pending.json
.venv/bin/python tools/bench/herdr_upgrade.py run --manifest bench/manifest.json \
  --policy bench/policy.json --subject candidate --scope first-baseline \
  --allow-native --authorization native-bench-approval-01 --output bench/candidate.json
.venv/bin/python tools/bench/herdr_upgrade.py compare --manifest bench/manifest.json \
  --policy bench/policy.json --candidate bench/candidate.json --output bench/decision.json
```

These are future, separately authorized commands. Outputs must be new files; atomic
publication refuses existing files, including symlinks. Calibrated policy references
must resolve to the calibration and original absolute policy beside the policy file.
Comparison rechecks private execution originals, their byte digests, expected versus
actual argv, subject identity, timing and normalized public arrays. Public reports
contain logical path labels and `normalized_argv`; the private manifest and raw argv
must not be published. The server binary is represented as `<HERDR>` in reports.

## Implemented execution and its evidence limits

Native execution verifies a new outside-repository root, exact candidate bytes,
private originals, synthetic sentinels, isolated HOME/XDG and default configuration.
It checks the existing configuration file with the official `herdr config check`
before starting a dedicated session. An existing server is refused. Config validation
and public schema/ping checks are required; no private upstream interfaces are used.
The fixed executable fixture is selected as the isolated machine's editor, launched
through `work open edit --new` in a new pane. It accepts no arbitrary command/argv.

Each mode/batch has immutable synthetic checkouts and a strict
`.rotom-bench-v1.json` anchor. Pane-specific ready/count files require the expected
native pane set and private control directory. Warmup/measure barriers carry only
run ID, phase and absolute monotonic start. Output is actually written by the
producer into the new terminal PTY: 128-byte ASCII lines at 512 lines/s, with a
60-second warmup and full 300-second measurement. Target counts are 153600 lines
and 19660800 bytes per producer per measurement. Runner stdout is not this load.

The matrix includes idle/output 1/10/30, nine Git checkouts across three projects
with three producers each, detached idle/output 30, two PTY clients at 120x40 and
80x24, 30 resize/focus rounds, and 300 additional terminal/client cycles. Project
controls exercise 100 repeats and concurrency 2/10 against the native pane set.
Churn samples six 60-second settled checkpoints and a 30-minute tail. Warm enter,
reuse and new-role paths use at least 200 samples per batch; attach probes target
only the verified synthetic record producer with a fixed nonce. Cold startup uses
30 new sessions per batch and reports median/range without p95. All paths retain
unknown results rather than replaying operations.

Procfs sampling records visible server, helper, client and producer CPU separately
with PID plus process starttime identity, 1 Hz RSS, process and FD observations.
Server-group RSS adds server/helper RSS and therefore counts shared pages more than
once. Sampling can miss short peaks. Critically, procfs polling cannot prove complete
CPU accounting for processes that exit between samples. `coverage.cpu_complete`
therefore remains false and native reports remain invalid/unverified for required
CPU coverage. No performance PASS is available from this backend alone. PSS and
wakeup are optional missing evidence; context switches are not called wakeups.

PTY creation, resize and transport closure are executable controls, not proof that
Herdr accepted a client, applied a particular shared-size rule or performed native
prefix-detach. Attach nonce receipts require a current native pane and the producer's
verified foreground PID/starttime before input; missing receipt remains unverified.
Native shared-size semantics and all required fault/context/cold-recovery cases need
actual behavior evidence. The manifest lists required correctness case IDs, so a
partial successful producer run cannot silently satisfy them. Default pytest uses
fake sockets/processes/clocks and does not establish any native result.

Cleanup rechecks pane/terminal/workspace identity and closes only objects created in
the dedicated run. An empty, confirmed owned server may be stopped; cold-start
sessions contain only their verified initial synthetic objects. Unknown outcomes or
unclassified objects preserve the server, private directory and evidence. Never
stop a production server to obtain benchmark access. Inspect preserved objects
explicitly before deciding on cleanup. Execution gaps and native evidence gaps must
be reported separately; helper tests do not prove execution of the full native loop.

## Decisions and rollout

Correctness failure takes priority over invalid performance. Missing required data,
uncalibrated policies, incomplete CPU coverage, unresolved noise or split batches
produce unverified results. Each regression requires both relative and absolute
thresholds, with the predeclared absolute near-zero rule; absolute budgets apply
independently. All three batches must agree. Optional missing evidence is reported
per item without blocking otherwise sufficient scopes. Null measurements require
reasons and are never converted to zero.

A pass is evidence, not rollout authorization. Any later canary or future-default
change needs separate approval and affects only new work. Preserve existing servers,
long-running tasks and private state. Rollback has three independent parts: program
selection, managed configuration rollback, and native persisted-state compatibility
or a verified state copy. Never assume an old binary can read newer state, and never
call layout restoration process recovery. Use the [report template](templates/herdr-upgrade-report.md)
with four task states: 已完成、进行中、失败待决策、环境不足未验证.

For `runtime` and `full-stack`, one run executes both subjects on the same machine.
`--output` corresponds to `--subject`; `--paired-output` records the other subject.
Both outputs are checked for new, distinct names before execution. A failure during
publication preserves any already published evidence and returns 4 or 6; it never
removes that evidence. `first-baseline` and `calibrate` reject paired output.

```sh
.venv/bin/python tools/bench/herdr_upgrade.py run --manifest bench/runtime.json \
  --policy bench/runtime-policy.json --subject candidate --scope runtime \
  --allow-native --authorization native-bench-approval-02 \
  --output bench/candidate-runtime.json --paired-output bench/baseline-runtime.json
```

The frozen order seed shuffles cases and alternates AB/BA for each workload/mode
in each batch. Isolated roots derive from subject and batch without changing the
manifest's identity. Both reports share `paired_run_id` and `paired_schedule`,
including planned/actual orders and both subjects' monotonic windows. Compare
requires identical pair identity, the frozen schedule, nonoverlapping ordered
windows and producer windows inside the proper subject interval. Current measured
A data is separate from its prior accepted receipt: `acceptance_ref` and
`acceptance_digest` bind a prior PASS report whose release/asset/client/server/input
identity matches A. Missing receipt or pair proof remains unverified.

Native source checks bind the current checkout HEAD, local target `main`, the
repository work-source digest (`termcfg.work.source_digest`), raw `uv.lock` bytes,
runner/measurement-tool bytes and all three schema bytes. Synthetic sentinel files
must be inside the outside-repository private evidence directory. The checked-in
manifest contains fictitious source/asset identities and cannot bypass these gates.

The CLI authorization label must exactly match the manifest's nonempty audit label
before native preflight; controls, paths and authentication URLs are rejected as
labels. This receipt binding still does not grant user authorization. Client
`--version` is checked against the declared disk-client version, independently of
server ping. Configuration bytes and parser acceptance are observed. Rules and integrations can use explicit origin fingerprints rather than exported
rule bytes. Set `inputs.rules_identity_kind` to `builtin-origin-fingerprint` and
`inputs.integration_identity_kind` to `disabled-origin-fingerprint`. Their digest
fields hash the canonical fingerprint objects. An omitted kind retains the older
byte-digest meaning; it cannot silently become a verified origin fingerprint.

The official `server agent-manifests --json` command is pinned to the owned socket
through `HERDR_SOCKET_PATH=/proc/self/fd/...` and an inherited FD. Every audited
agent must report bundled source with no remote/cache/override/error state. The
read-only `integration status` command uses the isolated HOME; all audited targets,
including the experimental target, must report not installed. The rules fingerprint
contains the exact candidate asset digest and sorted public agent/source records.
The disabled-integration fingerprint contains asset/configuration digests and sorted
target/status records. It contains no installation paths. Unknown or incomplete
sources, installed integrations, digest/kind mismatches or missing private originals
leave required effective-input evidence unverified. `origin-audit.json` records the
public tagged source files and byte digests used to audit this subset. A future
release with a different target set needs another audit, not relaxed validation.

Raw official replies and their paths stay in outside-repository 0600 identity
receipts under a 0700 directory. Public `origin_receipts` contain only kinds,
fingerprint digests and logical evidence references. Offline comparison recomputes
the fingerprints from those originals and binds asset, config and subject identity.
These fingerprints prove origin and disabled state; they do not claim that the
public API exports effective rule bytes.

## Preflight, bounded observations and duration

`estimate` is offline and starts no host:

```sh
.venv/bin/python tools/bench/herdr_upgrade.py estimate \
  --manifest tests/fixtures/herdr-bench/v1/manifest.json
```

The frozen full matrix has 11 workload/mode cases and three batches. Per subject,
60-second warmup plus 300-second measurement windows total 11880 seconds. Churn
adds six 60-second settled checkpoints and one 1800-second tail per batch, another
6480 seconds. Thus fixed workload windows total 18360 seconds (5h06m), plus the
132 seconds of explicit phase barriers: **at least 18492 seconds (5h08m12s) per
subject**, or **36984 seconds (10h16m24s) for an A/B pair**. This excludes Git/setup,
2400 warm-path operation samples, 90 cold starts, churn operations and cleanup.
Calibration and first-baseline together cost at least the same two-subject duration.
Output windows alone write 4187750400 bytes per subject; warmup adds 837550080
bytes. These counts describe workload, not successful measurements.

Native preflight prints duration and coverage limitations before executing hosts.
This machine's procfs sampling cannot account for all short-lived CPU. Experiments
with inherited perf task-clock cover own short children, threads and daemonized
descendants, with explicit enable/disable acknowledgements; they still differ from
complete `RUSAGE_SELF + CHILDREN` user+system accounting. Task-clock labels alone
cannot establish kernel exclusion. The public Linux task-clock implementation uses
scheduled context time; see [kernel implementation](https://github.com/torvalds/linux/blob/v5.10/kernel/events/core.c)
and [perf control documentation](https://github.com/torvalds/linux/blob/master/tools/perf/Documentation/perf-stat.txt).
The installed tool has no supported user_time/system_time tool events, and this
machine had no prepared delegated cgroup at that historical checkpoint. Perf counters are therefore parsed
strictly as separate task-clock-seconds and never substituted for frozen CPU budgets.
No optional perf backend or new accounting daemon is installed.

Without a valid `--cpuacct-delegation FILE` or explicit `--allow-incomplete-cpu`,
native run/calibrate stop with dependency exit 5
before host execution. This explicit flag permits observation with incomplete
coverage, not acceptance. To limit an observation, `run --case output-1:output
--batch 1` selects one frozen case and batch in first-baseline scope. The manifest
remains the complete matrix; the resulting report records
`explicit_partial_measurement`, stays invalid and cannot establish a baseline.
The non-churn case retains 60-second warmup, 300-second measure and 4-second
barriers (at least 364 seconds, plus setup/cleanup). Churn is at least 2524 seconds.
`--case` is rejected for calibration and A/B upgrade runs. Namespace isolation may
be requested with `--isolated-netns`; neither flag authorizes a native run by itself.

Only an explicit `--case` together with `--allow-incomplete-cpu` permits a diagnostic
under a pending policy. The report retains that policy digest and an unverified
`pending-policy-diagnostic` record; it does not invent approval, budgets or freeze
timestamps. This evidence cannot be promoted into an accepted baseline. Full runs
and calibration still require a frozen policy. An explicitly authorized diagnostic
may inform investigation; it does not retrospectively approve a performance policy.

The initial user/network-namespace diagnostic on the reviewed machine did **not**
reach warmup or measure: zero valid samples were collected in that historical
stage. Its first startup exposed a Unix socket pathname
length limit; the runner now uses compact case/session names and checks the longest
client-socket path before native subprocesses. Choose a short, new isolation root;
long roots fail with configuration exit 2. This does not relocate sockets outside
the protected owned directory.

Default tool-sandbox startup returned EPERM; even self-child ptrace was denied there.
A separately controlled startup proved Herdr can start in the new user/network
namespace. That experiment then exposed a distinct boundary: mapping only the
calling UID/GID leaves host-root ancestors unmapped, so the existing socket-client
ownership check correctly rejects them. The namespace helper now detects unmapped
trusted root ancestors before reexecuting the runner and returns dependency exit 5.
No socket ownership check was relaxed. The sole successful probe server was empty,
verified through its protected pinned socket outside the namespace and stopped;
no active producer was created. Those historical failures are environment/runner
evidence, not Herdr performance results. This machine remains the test environment;
the explicit offline-socket path below preserves its UID view and independently
proves the narrower socket policy.

## Explicit offline socket entry

For the fixed synthetic workload, `run` and `calibrate` also accept
`--offline-sockets`, mutually exclusive with `--isolated-netns`. The fixed helper
uses the already installed libseccomp, sets no-new-privileges, and returns EPERM
for `socket` and `socketpair` when the family differs from AF_UNIX, and for
`io_uring_setup`. It closes inherited nonstdio descriptors and refuses socket
stdio whose actual domain is not AF_UNIX. It only executes this repository's
benchmark runner, retains the caller UID/GID and ordinary root-owner view, and
does not install a service, request privileges or relax socket ownership checks.

The kernel documents filter inheritance across fork/exec and the no-new-privileges
requirement in its [seccomp filter documentation](https://kernel.org/doc/html/latest/userspace-api/seccomp_filter.html).
This is a narrow socket-creation policy for the trusted fixture. It is not a full
network sandbox for arbitrary malicious programs; Unix IPC itself can communicate
with other services or transfer descriptors.

The runner independently checks actual NoNewPrivs/Seccomp state, IPv4/IPv6 socket
and socketpair EPERM results, an AF_UNIX data round trip, denied io_uring creation,
visible protected root ownership and safe descriptors. An internal reexec argument
does not substitute for these checks. Before each native case, it repeats the
checks and records a new 0600 private proof under the outside-repository evidence
directory. Reports use `isolation.evidence_ref=offline-sockets-seccomp` and required
evidence containing only a logical proof reference/digest. Compare verifies those
originals and binds helper bytes, subject identity and case; it does not call this
mode a network namespace.

The first reexec proof still rejects every inherited nonstdio descriptor. When the
CPU backend is active, later checks permit only its 18 registered close-on-exec
cgroup descriptors, after rechecking their fixed directory/file identities and
permissions. Any other live descriptor, incomplete registry or inheritable handle
fails. The check neither closes nor reopens those handles.

```sh
.venv/bin/python tools/bench/herdr_upgrade.py run --manifest bench/partial.json \
  --policy bench/pending-policy.json --subject candidate --scope first-baseline \
  --allow-native --authorization native-diagnostic-approval-01 \
  --offline-sockets --allow-incomplete-cpu --case output-1:output --batch 1 \
  --output bench/partial-output.json
```

This command still needs explicit native authorization and fresh private paths.
CPU coverage remains incomplete, a partial diagnostic remains invalid, and a
pending-policy observation cannot become a baseline. All full-matrix, frozen-policy,
same-machine pairing and correctness gates remain in force. Default pytest uses
fake kernel/libseccomp operations and installs no real filter or third-party host.


The subsequent explicit offline-socket diagnostic on this same machine completed
one `output-1:output`, batch 1 window: 60.000071 seconds of warmup produced
30,720 lines / 3,932,160 bytes; 300.000039 seconds of measurement produced
153,600 lines / 19,660,800 bytes. Actual seccomp checks and bundled/disabled origin
fingerprints passed. The case root used an independently checked sticky-root
`tmpfs` filesystem after the disk-backed temporary filesystem fell below the
256 MiB guard; the manifest records that distinct environment. This shared-machine
diagnostic included other workloads and is not comparable with a disk-root baseline.

The report remains **partial / invalid**, with no accepted baseline or approved
budget: complete short-lived CPU, client-ready and dimension evidence remain
unverified. The runner returned ownership-conflict exit 4 after closing the final
producer: Herdr created a fresh default pane, so the dedicated-server empty-object
check preserved it. Separate owned-root inspection then confirmed its identity,
stopped only that test server, and verified session disappearance. Both phase
receipts and the failure/cleanup evidence were retained privately; no terminal
body is published. The measured runner was frozen before a subsequent fake-tested
FD-cleanup correction to interactive attach, so this run does not claim native
coverage of that later fault-path correction.

The earlier cleanup correction retained the final registered fixture pane while
closing the others. A later projects-27 diagnostic exposed an exit-1 close at a
workspace boundary, despite passing its warm latency and concurrency checks.
The revised dedicated-case cleanup first queries every current pane and requires
an exact, nonempty match with all registered pane/terminal/workspace identities,
with no duplicates, missing or unknown objects. Only then does it use the pinned
socket to stop the complete dedicated server once. It leaves `confirm_close`
enabled. Ambiguous outcomes preserve the server and evidence without retries.
A new complete projects-27 single-batch diagnostic has verified normal client/server
exits and fresh empty delegated groups with this procedure. It remains explicitly
partial; full calibration and baseline acceptance are pending, and the earlier
failed diagnostic remains failed.

A historical short native cleanup probe exercised the earlier path under the same
actual offline-socket policy: a new synthetic Git workspace and two ordinary test
panes were created, the first pane was closed, and the dedicated server was stopped
with only the second registered pane remaining. Session discovery confirmed absence;
no automatic fallback pane remained. This probe verifies cleanup, not a new timing
window or the still-unverified full benchmark.


## Native CPU and UI proof preparation

The optional Linux v1 backend consumes a private administrator receipt through
`--cpuacct-delegation PRIVATE_RECEIPT`. `tools/bench/cpuacct_admin.py prepare` is an
explicit administrator step from the ordinary user's sudo session; it creates only
four empty accounting groups under that session's current cpuacct source. It does
not set limits or move existing processes. Keep its receipt outside the repository
with mode 0600 in a 0700 directory. This administrative helper uses the system
Python standard library; the benchmark itself continues to use repository Python
3.11 or newer. Patch versions are evidence, not exact runtime requirements.

Before a full run, prove short-child, thread and orphan accounting on that same
host, then run a separately labelled partial window. A complete 300-second CPU
window requires 301 identity-bound kernel snapshots, start/end within the fixed
50 ms tolerance, correct driver/server/client/producer membership, and actual
user plus system deltas. Average cores use the actual endpoint interval. Optional
per-MiB costs divide by each case's actual measured output bytes. A partial window
cannot establish a baseline, even when its individual CPU proof is complete.

For the reviewed default desktop geometry, a fixed record producer proves each
owned client's input path and actual pane size. Before sending a nonce, the tool
waits for raw mode within its existing five-second deadline; it treats a safe,
newly created zero-length receipt as pending its first write. Malformed content,
permissions or identities still fail. Both UI sizes are changed before a 250 ms
PTY drain, followed by the first strict nonce/layout check. The pause stays inside
the fixed workload window. This accounts for the upstream
[100 ms resize poller](https://github.com/herdrdev/herdr/blob/v0.9.5/src/client/terminal_geometry.rs#L120-L165);
it does not grant each client independent TUI dimensions. Attach latency includes
startup and raw-mode waiting. No input retry masks a failed geometry check.

After every case, retain failures and verify owned child processes have exited.
After the owned server exits normally, wait at most five seconds for its server,
client and producer groups to become empty before the next case. A nonempty group
may continue waiting; malformed data, changed identity or permissions fail
immediately. This is outside measurement windows and sends no signals or PID moves.
Keep the delegated groups for the full authorized calibration and baseline. After
all benchmark work ends, the administrator runs `cpuacct_admin.py cleanup --token
TOKEN` using the matching private receipt; cleanup verifies root records, boot and
inodes and refuses occupied or unexpected groups. Never kill or move a process to
make cleanup pass.

Membership snapshots open a fresh read-only `cgroup.procs` descriptor beneath each
pinned role directory, verify it against the original inode, owner, mode and cgroup
filesystem, then close it before any spawn or descriptor audit. The 18 persistent
descriptors remain pinned. On cgroup v1, an existing open context can reuse a cached
PID list; seek or pread alone does not refresh that context. This follows the
[Linux 5.10.134 pidlist implementation](https://github.com/gregkh/linux/blob/v5.10.134/kernel/cgroup/cgroup-v1.c)
and a separate native freshness probe on the sole test host. It does not assume the
host vendor kernel is identical to that upstream tag. CPU counters keep their
existing identity-checked read path; member PID/starttime checks remain strict.


Successful UI cleanup sends only the reviewed native `Ctrl+x d` detach sequence
to the pinned owned test PTY, under a five-second deadline with PID/starttime and
raw-mode checks. It requires UI exit 0 before closing the PTY or stopping the
server. Attach timing ends after fixed input readiness, before this cleanup. A
failed or uncertain UI is retained as failed evidence; closing a PTY in failure
cleanup never rewrites its recorded exit code into success. The native-client
recipe keeps its expected exit at 0.


A fresh record-mode UI also waits for its run-bound `RBREADY:` marker in actual
rendered output. The fixed producer repeats this marker after each valid nonce
so echoed test input cannot permanently scroll it out of view. The observer keeps
only a marker-sized tail in memory and stores no terminal text. Raw mode is still
checked, and the first strict nonce must arrive; neither a marker nor a fixed
sleep substitutes for that input proof. The marker wait is part of attach latency
and the revised fixture identity, with no persistent client state or helper daemon.

## Explicit acceptance of the sole calibration warmup deviation

On 2026-10-20 the owner accepted review of the identified calibration-only
warmup deviation: one producer counted 30,719 rather than 30,720 lines, a
128-byte deficit. Its formal measurement and CPU windows are separate and all
formal output counts are complete. This is a disclosed, report-bound exception,
not a previously declared tolerance. The original calibration stays invalid.

A private, one-run reviewer binds the explicit approval, immutable report and
original evidence digests, exact single row, phase/run/pane/process identities and
nonoverlapping formal window. Every other producer row, correctness/UI/original
check, required metric and absolute budget stays strict. The frozen runner,
three schemas, manifest and measurement inputs remain byte-identical; derived
noise and budget parameters cannot change. The reviewer saves a separate
acceptance receipt and policy, then rechecks them before using the existing Python
comparison API. Bare CLI comparison continues to reject the invalid calibration
reference. Preserve the schema-valid comparison report for future baseline
acceptance and retain separate review provenance; do not publish the reviewer as
a generic bypass or apply this exception to a later candidate.

### Target-main reference advance during this immutable first baseline

The first start stopped before measurement because shared main advanced while the feature checkout stayed unchanged. A separately named manifest records the new target reference. A private verifier reconstructs it from the original manifest and permits only the explicit manifest ID suffix, source.target_main, and digest to differ. The original calibration is checked against its original manifest; the strict new candidate is checked against the new manifest, with all measured inputs and the reviewed policy identical. This explicit proof does not rely on verify_calibrations omitting a manifest-reference check. Any change to candidate source, dependencies, asset, configuration, workload, sampling, or isolation inputs requires fresh calibration. Both manifests, the failed start, and original reports remain intact. This establishes evidence for the frozen feature candidate only; integration after merging the newer main needs its own checks.

## Accepted sole-host first baseline: 2026-10-20

The frozen feature candidate has an accepted v0.9.5 first baseline. See the [public acceptance summary](../specs/005-herdr-project-workspaces/acceptance-summary.json) and [layered evidence](../specs/005-herdr-project-workspaces/implementation-evidence.md). The independent three-batch run took about 5h39m30s: 33 complete CPU windows, 45 correctness checks and all 426 output phase counts passed; required unverified items were zero. Optional unverified items remain explicitly unverified. The original calibration remains invalid under its narrowly accepted warmup exception; the new candidate report is strictly valid.

The independent canary and configuration/binary/state rollback guards are accepted, including a protected native-state copy and an explicit compatibility-unproven stop. The latter is not proof of downgrade compatibility. Every registered test server/task was stopped normally; the four empty delegated CPU groups were removed using the original administrator receipt. Private raw reports, failed attempts, acceptance receipts and source snapshots are retained; public summaries do not rewrite them. This result applies to the frozen feature checkout on the tested Linux server and does not establish A/B improvement, integration after merging newer main, or a production entry cutover.
