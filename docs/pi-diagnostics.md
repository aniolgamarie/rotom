# Pi diagnostics and verification

## Layered doctor results

`agentcfg doctor` reports Pi `capabilities` separately for selection, configuration, deployment, dependencies, load evidence, authentication observations, and execution evidence. Installation does not prove loading/execution. An unbound bootstrap model reports `PI_MODEL_UNBOUND`.

| Observation | Meaning |
| --- | --- |
| Required runtime missing/damaged | Report diagnostics and return 5 |
| Authentication `not-inspected` | No Pi/Codex account file was read to infer login |
| `observed-ready` | Matching historical authentication observation, with timestamp |
| `pending-login` | Matching observation requires login |
| `not-required` | Capability needs no authentication |

Explicitly allow evidence files through private configuration:

```toml
[overrides.profiles.pi-default.agent_options.diagnostics]
evidence_root = "/absolute/private/evidence"
evidence_paths = ["load.json", "authentication.json", "execution.json"]
```

Files must satisfy `agents/pi/schemas/evidence.schema.json`. Doctor stage observations use `test_case_id = load | authentication | execution`. Only matching native/live evidence for the target identity/platform can be verified; mock records never become native-load or real-authentication evidence.

Identity covers lock, runtime, policy, rendered content, complete selected skills, roles/models, and machine contract. Changes to policies, models, rules, or routes invalidate old observations. The diagnostic evidence file list is not execution identity, so adding evidence does not itself expire existing records.

`doctor --live` sends HEAD reachability probes only to explicitly selected provider/MCP HTTP/Web service origins and routes. It does not call models, inspect native accounts, or follow redirects. Environment proxy/NO_PROXY does not alter routing. Missing routes report `explicit-route-required`. Supported probes use direct access or unauthenticated HTTP proxies; authenticated/HTTPS proxies remain explicitly unverified without direct fallback. HTTP 401/403 establishes a response, not login or model readiness. Public fetch without a selected target reports `public-target-not-selected`; public-only Web without credentials/subscription models reports authentication `not-required`.

## Fixed-scope reports and release checks

```sh
.venv/bin/python scripts/verify-pi.py --report-only \
  --scope /absolute/pi-scope.json --evidence-root /absolute/private/evidence \
  --output /tmp/pi-status-new.json

.venv/bin/python scripts/verify-pi.py --check-release \
  --scope /absolute/pi-scope.json --evidence-root /absolute/private/evidence \
  --output /tmp/pi-release-new.json
```

- `report-only` returning 0 means report creation succeeded, even with no evidence.
- `check-release` returns 0 only when every required and selected optional item meets its required evidence tier for the frozen scope. Missing/failed/stale evidence returns 1.
- Invalid schema, paths, or identity digests return 2.
- Each report is a new 0600 file; concurrent creation never overwrites an existing report. Use a fresh output name.
- Only relative evidence paths listed by the scope are read. Neighboring accounts, reports, and other scopes are not scanned.
- `not-selected` records an explicit selection state, not execution success. Missing login, machines, or authorization does not mean unselected.
- Scope/evidence changes invalidate previous approval. Automatic revisions cannot reduce required scope.

## Isolated validation

```sh
.venv/bin/python scripts/verify-pi.py --tier mock --case all \
  --output /tmp/pi-mock-new.json
```

The runner creates a temporary HOME and executes default pytest plus restricted Node mock suites. Raw output goes to the adjacent private `.artifacts` directory; reports retain commands/statuses. Any failed or unavailable suite prevents an overall pass. Default validation does not start third-party hosts.

Native/live runners exist, but execution requires separate explicit authorization. Historical candidate `9d6a9270…` recorded 81/81 selected Linux x86_64 checks and four-profile, two-path cold reconstruction. That is historical evidence, not current-checkout validation. Current Pi is 0.84.4 and its full dependency lock was rebuilt for the shared-run change; current acceptance remains scope-specific. A version probe or Python/mock pass cannot replace matching native/cold evidence after source, lock, runtime, or policy changes. See [testing](testing.md), [known issues](known-issues.md), and [roadmap](roadmap.md) for retained results and open platform/live work.
