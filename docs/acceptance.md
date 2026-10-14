# Acceptance summary

The maintained validation policy and current results are in [testing](testing.md) and [release verification](release-verification.md). Historical source and scope records remain under `specs/`; raw machine-specific handoffs and logs have been retired from the publication tree.

| Surface | Current statement |
| --- | --- |
| Manager offline contracts | Baseline identified one stale assertion; narrow fixes passed their related suite. Final candidate results are recorded separately. |
| DSH | Current recipe selects RC2 / TUI 0.15.0. Historical native functionality exists; Perry's full safety gate failed and the user accepted its documented limitations. |
| OMP | Official 18.8.6 selected; Linux native evidence exists for specific versions/operations. Other platform and live coverage remains bounded. |
| Pi | Historical Linux software scope completed for lock 9d6a9270; current lock/source mismatch blocks new deployment. |
| termcfg | Independent isolated configuration/service contracts; no automatic inference of cross-platform native success. |

PASS, FAIL, BLOCKED, and NOT RUN must remain distinct. Do not equate a successful installation, a mock result, or an old acceptance report with current native compatibility. See [known issues](known-issues.md).
