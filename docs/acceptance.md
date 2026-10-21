# Acceptance summary

The maintained validation policy and current results are in [testing](testing.md) and [release verification](release-verification.md). Historical source and scope records remain under `specs/`; raw machine-specific handoffs and logs have been retired from the publication tree.

| Surface | Current statement |
| --- | --- |
| Manager offline contracts | Baseline identified one stale assertion; narrow fixes passed their related suite. Final candidate results are recorded separately. |
| DSH | Current recipe selects Core `0.2.1-rc.2`, official npm TUI `0.16.1`, and Perry `0.13.7`. Current-main integration passed 975 affected Python checks, 76 Node checks and six isolated native groups including TUI/Perry/Teams. Main's revised Pi fixtures pass; original-base failures remain historical. Historical lifecycle/audit fixes are not claimed. See the [integration acceptance](acceptance/dsh-main-integration-20261021.md) and [ecosystem record](acceptance/dsh-ecosystem-upgrade-20261021.md). |
| OMP | Official 18.8.6 selected; Linux native evidence exists for specific versions/operations. Other platform and live coverage remains bounded. |
| Pi | Complete lock rebuilt; Linux pi-default installation, concurrency and sandboxed-resource evidence is recorded in the [refactoring record](design/project-refactoring.md). Historical 9d6a9270 feature results do not validate later candidates. |
| termcfg | Terminal-only configuration/plugin contracts and explicit legacy metadata migration: 106 isolated tests passed. Existing proxy services were untouched; native/platform acceptance was not renewed. |

PASS, FAIL, BLOCKED, and NOT RUN must remain distinct. Do not equate a successful installation, a mock result, or an old acceptance report with current native compatibility. See [known issues](known-issues.md).
