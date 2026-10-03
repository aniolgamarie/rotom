# Permission-control evaluation runner

`run.ts` only reviews the frozen 240-case fixture. It never executes `action.command`, imports a shell
executor or host CLI, creates a permit, or calls the installed-only tiny fallback. Before parsing cases it
verifies the byte digest over `fixture-schema.json`, `cases.jsonl`, and `labels.json`.

The default mode uses a fixed fake reviewer which always returns a valid conservative `ask`. Deterministic
policy and native gates still run through the production policy module. The fake reviewer does not read
`expected`, `category`, `rationale`, or `evidenceExpectation`; those fields are only fixture metadata for
later comparisons. Fake reports leave SC-001 null and identify real model authorization semantics as
unverified.

All environment, effect, and user-message context comes from the frozen fixture and is marked
`frozen-simulated`. It is not host proof. State-sequence cases drive a real `PermissionLedger` with a fake
monotonic clock for supported cancellation and generation changes. Observations that the runner cannot
obtain remain `null` and carry a closed `unverifiedReasons` value on that case. Input events alone are not
reported as successful runtime observations.

Only messages whose role is `user` and whose source is authenticated, interactive, and non-synthetic enter
the review envelope. Dropping any supplied message makes that simulated context incomplete. Structured
restrictions use a closed mechanical mapping over the frozen effects; natural-language permissions such as
`allow-write` stay unknown rather than being filled in as satisfied.

From the repository root, fake mode is:

```sh
/locked/path/to/bun agents/omp/packages/omp-permission-control/evaluation/run.ts \
  --mode fake \
  --repository-root "$PWD" \
  --fixtures "$PWD/tests/fixtures/omp/permission-control" \
  --platform linux-glibc-x64
```

Output defaults to stdout. `--output /new/private/report.json` uses exclusive creation after fixture and
source identities have been validated and evaluation has completed. The output must be outside the plugin
tree, frozen fixture directory, and host patch directory so writing a report cannot change the identity it
records.

Real mode is intentionally unavailable without an explicitly selected adapter and public identity:

```sh
/locked/path/to/bun agents/omp/packages/omp-permission-control/evaluation/run.ts \
  --mode real \
  --repository-root "$PWD" \
  --fixtures "$PWD/tests/fixtures/omp/permission-control" \
  --platform linux-glibc-x64 \
  --service-module /reviewed/absolute/evaluation-service.ts \
  --provider public-provider-id \
  --model public-model-id \
  --transport openai-completions \
  --output /new/private/report.json
```

The trusted module must export `createEvaluationReviewServices({provider, model, transport})` and return a
`ReviewServices` implementation. Selecting this module is a separate authorization step: the runner does
not read HOME, environment credentials, provider registries, or local accounts. It passes each review
request to `reviewOnce` at most once, omits fallback configuration, and never delegates to
`tinyInstalledOnly`. Real review uses the actual monotonic clock and cancellable timer. The selected adapter
must call `onInferenceStarted` exactly at its actual send boundary; the runner does not pre-count it. The
report's call count covers only this `ReviewServices` boundary; retries or fallback
inside the trusted adapter remain unverified and are explicitly labeled as such. Real evaluation is still
read-only review of frozen command text and does not authorize or execute any command.

The report computes identities from current bytes rather than accepting digest flags:

- `sourceDigest`: fixed ordered runner/core files participating in evaluation;
- `policyDigest`: `policy.ts` bytes;
- `fixtureDigest`: the frozen three-file digest;
- `pluginDigest`: the production complete plugin-tree algorithm, including evaluation files;
- `hostDigest`: ordered patch series and patch bytes.

These identities make a report attributable to one candidate. They do not replace the final build receipt,
host bridge handshake, real provider evidence, or results outside the frozen fixture.


## Mechanical fault observations

Fourteen frozen cases describe malformed evidence or a stale generation rather than unauthorized user intent.
The runner validates a well-formed positive control with the production decoder, injects the named frozen fault,
and requires the decoder to reject it. These cases are listed under `mechanicalCases` and make no model calls.
The original 240 case IDs, labels, and scoring denominators stay unchanged; 78 cases remain eligible for model review.
Cases with later natural-language restrictions still send the complete messages to the reviewer.

`metricSemantics.compoundCompleteRate` explicitly limits that metric to the input effect inventory. It is not an
observation of model effect coverage or authorization accuracy. Real response decoding and semantic results must be
reported separately. Supplemental cases, when used, are frozen before inference and reported outside the original
denominators.
