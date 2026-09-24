import { registerWorkflowCases } from "./fixtures/workflow-cases.ts";

registerWorkflowCases([
  "fallback-budget-exhausted",
  "terminal-resume",
  "worker-compaction-quota",
  "worker-compaction-failure",
  "quota-recovery",
  "fallback",
  "multi-job",
  "fallback-skip-network",
  "fallback-skip-telemetry",
  "fallback-skip-context",
  "fallback-skip-thinking",
  "network-recovery",
  "network-exhausted",
  "combined-features",
  "combined-tool-recovery",
  "model-control-race"
]);
