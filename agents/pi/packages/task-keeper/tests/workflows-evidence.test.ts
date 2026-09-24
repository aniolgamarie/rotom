import { registerWorkflowCases } from "./fixtures/workflow-cases.ts";

registerWorkflowCases([
  "worker-claim",
  "zero-tests",
  "details-only-error",
  "summary-hides-failure",
  "packet-overflow",
  "packet-overflow-no-abort",
  "all-skipped",
  "unknown-tests",
  "unread-review",
  "premature-review",
  "stripped-review-input",
  "forged-artifact",
  "recovered-tool-error",
  "review-reuse",
  "optional-failure",
  "optional-disallowed",
  "artifact-loss",
  "runtime-upgrade"
]);
