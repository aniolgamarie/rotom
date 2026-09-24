import { registerWorkflowCases } from "./fixtures/workflow-cases.ts";

registerWorkflowCases([
  "cancel-after-edit",
  "workspace-failure",
  "spawn-failure",
  "baseline-environment-failure",
  "invalid-plan",
  "silent-build",
  "interrupted-zero",
  "candidate-edit",
  "inspect",
  "fix",
  "repair",
  "mutating-check",
  "check-input-change",
  "check-approval",
  "build-repair",
  "environment-failure",
  "binding-approval"
]);
