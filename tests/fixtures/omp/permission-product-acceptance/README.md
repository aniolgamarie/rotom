# OMP permission product acceptance baseline

The routing baseline is `routing-policy.json`, which freezes the new model-first contract over the existing 11,473-row synthetic-public corpus at `../command-scenarios/corpus.json.gz`. Its source SHA-256 and category counts are recorded in the policy file. The original corpus and its historical labels remain unchanged.

The corpus has 11,472 nonempty command strings that must reach model review and one empty command rejected by independent required-input validation (`command.length == 0`). That row remains in the report and is not a permission-routing exception. The pre-model permission exception list is empty. The source is synthetic-public and uses fixture placeholders/redacted paths; commands that read a credential source do not thereby contain credential values. Shell syntax uncertainty still goes to model review.

For model-routed rows, a deterministic fake model answers `ask`, and commands must not execute. This checks routing and decision handling only. It does not validate semantic risk labels, model judgment, or whether arbitrary real command text may safely be sent to a model.

An initial structural preview printed the old `expected` status field for the first eight source records. Those statuses were not used to set any routing expectation; the contract defaults follow the updated model-first standard.
