# Pi support boundary

The Pi adapter is implemented, but the current checked-in recipe and lock are mismatched. New deployment paths reject the lock. Resolve PI-LOCK in [known issues](../known-issues.md) before claiming a fresh usable Pi installation.

## Historical acceptance

The narrowed Linux x86_64 software scope `001-unify-pi-capabilities-linux-software` revision 1 completed for candidate lock `9d6a927093f066c9428a5c193a636c4d73c5e64c946d24dc6a08185cf3f0dbf0`: 81 passed, no failed/not-run/stale cases in that selected scope. The value is a lock digest, not a Git commit. Four profiles were included: `pi-default`, `pi-managed`, `pi-codex`, and `pi-cursor`, with mock/native and two-path cold reconstruction evidence at that time.

Other platforms and real-account/service checks were explicitly moved outside that scope. They were not converted into passed tests. The broader historical matrix still contained unexecuted cases. Raw machine output was retired during publication cleanup; scope and project records remain in `specs/001-unify-pi-capabilities/`.

## Current claims

| Capability | Status |
| --- | --- |
| Adapter and isolated contracts | Implemented; see current automated results |
| Current source/lock closure | FAIL / PI-LOCK |
| Current native and cold reconstruction | NOT RUN for the prepared source snapshot |
| Other operating systems / architectures | NOT RUN |
| Authorized Codex/Cursor/API/service validation | Separate authorization and current-candidate evidence required |

An existing deployed runtime uses its saved contract; do not assume it fails solely because the repository lock is stale. Conversely, its successful launch would not repair or validate the checked-in lock. See [Pi guide](../pi.md), [testing](../testing.md), and [release scope](../releases.md).
