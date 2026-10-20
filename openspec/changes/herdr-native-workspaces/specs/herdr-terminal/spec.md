## ADDED Requirements

### Requirement: Herdr is an explicit optional terminal component

Rotom SHALL allow an explicit `herdr` component selection without enabling it for existing zsh/tmux selections. It SHALL manage only catalog-declared configuration files and preserve native sockets, session data, caches, logs and generated integrations.

#### Scenario: An existing terminal machine is used without Herdr

- **WHEN** an existing zsh/tmux machine is validated, planned, applied or recovered
- **THEN** it retains its component selection and current recovery semantics without acquiring Herdr targets

#### Scenario: A private native configuration already exists

- **WHEN** a Herdr target has no matching Rotom ownership record
- **THEN** the existing explicit adoption and conflict process applies; the whole directory is not adopted

### Requirement: Installation and runtime checks are explicit

Version selection SHALL prefer a recent unmodified official stable release and recheck the latest stable release before initial installation and each explicit upgrade. The currently verified candidate on 2026-10-18 is 0.9.5; this SHALL NOT be a permanent exact-version guard or an assumed lower bound for all future compatibility. Installation evidence SHALL bind the selected release/tag, asset, checksum, architecture and source. Offline status and normal launch SHALL neither install nor update Herdr. Disk binary, running server, effective configuration, integrations and detection-rule provenance SHALL be reported separately.

#### Scenario: An older binary is found

- **WHEN** the selected executable reports 0.8.0 but has only metadata observation and no workflow acceptance
- **THEN** it is reported as unvalidated rather than accepted as a baseline; no running server is stopped and no download is started

#### Scenario: Disk and server versions differ

- **WHEN** disk and server versions differ
- **THEN** both identities are reported and required protocol/capabilities and acceptance records are checked; unsupported mutation is refused without restarting the server, while a version difference alone is not treated as proof of incompatibility

#### Scenario: A newer stable release becomes available

- **WHEN** a newer official stable release is discovered during explicit installation or upgrade preparation
- **THEN** it can enter isolated evaluation without changing a hardcoded 0.9.5 equality check; promotion requires the applicable compatibility, regression and benchmark evidence

### Requirement: Terminal first configuration has native diagnostics

The managed candidate SHALL use the approved prefix and quiet defaults, disable automatic Agent resume and background update checks, and exclude experimental pane history. Field names, enum values and title placeholders SHALL be checked against the selected release. A successful TOML parse SHALL NOT count as successful native loading, and successful reload SHALL NOT prove that startup-only settings changed.

#### Scenario: A candidate configuration is deployed

- **WHEN** an isolated native acceptance server loads the candidate
- **THEN** its diagnostics and applied values are recorded; user servers are not automatically reloaded

#### Scenario: Cached detection rules exist

- **WHEN** background manifest checking is disabled
- **THEN** the existing effective rule source and digest are still recorded; caches or overrides are not silently deleted

### Requirement: Recovery preserves process and ownership boundaries

Configuration rollback SHALL restore only declared managed configuration. It SHALL neither downgrade software nor rewrite native session state. Detach/reconnect SHALL be distinguished from cold server restart; layout restore SHALL NOT be reported as recovery of original processes.

#### Scenario: SSH disconnects while compilation runs

- **WHEN** the server remains running and the client reconnects
- **THEN** the acceptance records whether the same process survived, separately from restored layout

#### Scenario: The server has stopped

- **WHEN** a layout is restored
- **THEN** no historical build command or most-recent Agent conversation is automatically launched by Rotom

### Requirement: Integrations are optional and permission bounded

Basic terminal organization SHALL work without Agent integrations. DSH/Pi SHALL keep their deployed Rotom profile, cwd and HOME contracts. Integration inheritance SHALL be explicit through the existing environment policy; socket access SHALL NOT be treated as a status-only permission.

#### Scenario: An extension cannot use the socket under current isolation

- **WHEN** state reporting would require broader sandbox or socket access
- **THEN** the enhancement stays disabled and the ordinary terminal workflow remains available

#### Scenario: Codex is launched independently

- **WHEN** the configured entry requires per-pane association
- **THEN** it uses the explicitly selected no-daemon policy without changing global aliases, Pi delegation or active daemons

### Requirement: Validation is bound to actual scope

Evidence SHALL distinguish offline simulations, native isolated servers, real clients and real Agent sessions. Only tested platform/client combinations SHALL be reported as passed. Live hosts and real Agent smoke retain the repository's explicit authorization requirement.

#### Scenario: Interactive acceptance is unavailable

- **WHEN** only documentation and isolated simulations were checked
- **THEN** native and client results remain unverified, and unrelated completed checks are preserved

### Requirement: Upgrade comparisons are reproducible

The project SHALL maintain versioned synthetic workloads, measurement methods and a machine-readable report contract for comparing the last accepted release with a new stable candidate on the same environment. Benchmarks SHALL cover functional correctness, latency, CPU, memory, detach behavior and sustained growth without including real Agent cost in multiplexer measurements. Correctness failures SHALL block promotion; missing mandatory measurements or uncalibrated performance thresholds SHALL NOT count as passes. Optional wakeup/PSS measurements MAY remain explicitly unverified without automatically blocking an otherwise supported promotion or expanding permissions; unmeasured optional items SHALL NOT be reported as passed.

#### Scenario: The first accepted release has not been established

- **WHEN** only an observed old binary and an untested candidate exist
- **THEN** no performance baseline or regression pass is invented; initial measurements establish a baseline only after the corresponding acceptance gates pass

#### Scenario: Candidate rules also change

- **WHEN** an upgrade changes both the binary and the effective detection rules or integrations
- **THEN** the inputs and hashes are recorded separately and the comparison distinguishes fixed-input runtime measurements from the full candidate bundle

#### Scenario: A baseline and a candidate are compared

- **WHEN** authorized native benchmarks run
- **THEN** both versions use isolated native state and equivalent fixtures, terminal sizes and measurement methods; latency sample counts, distribution, resource units, noise policy, thresholds and unavailable measurements are recorded

### Requirement: Upgrade promotion and rollback preserve active work

A candidate SHALL be staged separately, evaluated in an isolated server, checked with actual clients and tried on new work before explicit promotion of future launches. Promotion SHALL NOT imply that existing servers were upgraded. Default upgrade behavior SHALL preserve active processes and SHALL NOT use experimental live handoff. Rollback SHALL distinguish executable selection, managed configuration and native persistent state; an old binary SHALL NOT be assumed compatible with state rewritten by a newer release.

#### Scenario: A candidate fails a blocking check

- **WHEN** input, target identity, cwd, permission, process survival or calibrated benchmark gates fail
- **THEN** promotion stops, the last accepted entry remains available, and the failure and a re-evaluation condition are recorded without terminating active work

#### Scenario: A newer server has written state

- **WHEN** rollback to an older binary is considered
- **THEN** compatibility is first tested with isolated synthetic state or an explicitly authorized protected copy; changing the launcher alone is not reported as state rollback or migration of running processes
