# Configuration state and recovery

Rotom manages declared files and fields while preserving native state. Configuration source, desired artifacts, installed software, deployed baselines, and native sessions are separate identities.

## Ownership and three-way comparison

Rendering is deterministic: it uses validated nonsecret input and produces bytes or desired field intent. It does not read the current native file to manufacture a desired whole document. Deployment compares baseline **B**, current native value **C**, and desired value **D**.

| Comparison | Result |
| --- | --- |
| C equals B | Update to D when needed |
| D equals B, C differs | Preserve and report user drift |
| C equals D | No rewrite |
| C and D both differ from B and each other | Conflict; stop unsafe writes |

Preserved drift is not silently accepted as a new baseline. Whole-file/field overlap, unsafe selectors, active instances, unowned nonempty files, and pending recovery retain their own conflict checks.

Initialization-only fields are different from continuously managed fields. If a declared mixed file already contains a user preference at its first initialization opportunity, that value is preserved and the opportunity is consumed. Repeated apply does not restore the initial preference. Unknown native fields remain intact. This is not bidirectional preference synchronization.

DSH native UI settings use this model where declared; Pi whole-file keybinding initialization and termcfg transactions have their own contracts. Always inspect the adapter's ownership declaration rather than generalizing one host's behavior.

## Transaction lifecycle

A stable owner record identifies the managed instance even after the first rollback. `current` stores managed baselines and a nonsecret launch contract. `previous` holds only the previous successful changed configuration generation. `pending` records interrupted multi-file work and recovery decisions.

Single files are written through a same-directory temporary file and atomic replacement. Multiple files use a journal and rechecks; this is recoverable deployment, not an atomic transaction across external processes. Failures and no-op operations do not rotate backups. A successful rollback consumes the previous backup and preserves newly added unmanaged data.

Private storage verifies ownership, permissions, path ancestry, links, and identity before writing. Existing unsafe or concurrently modified files are rejected, not repaired by broadening permissions or taking ownership. A private directory normally requires `0700`, a private ordinary file `0600`.

## Software and native data

`sync` stages a locked runtime, verifies its full declared shape and content, and activates it only after success. Installed runtime identity is separate from configuration generation. `run` launches the saved contract and does not implicitly install or apply.

Configuration rollback does not downgrade software or migrate sessions, OAuth databases, trust records, or logs. Never hand a database written by a newer host to an older host and call that tested recovery. Keep old and new native state isolated until a specific migration has been validated.

Activity leases prevent deployment over a running managed instance. They are not a sandbox against same-user arbitrary code. A background descendant can retain inherited descriptors; see LEASE-01 in [known issues](../known-issues.md). Do not delete a live lock to bypass diagnosis.
