import { buildReviewRequest, type ReviewBuildInput, type ReviewClock } from "../reviewer";

export function input(overrides: Partial<ReviewBuildInput> = {}): ReviewBuildInput {
  const hash = "a".repeat(64);
  return { session_id: "session", generation: 0, session_salt: "s".repeat(32), operation: "pwd",
    final_args: { command: "pwd" }, prepared_execution_id: {}, execution_binding: { digest: hash, local_ref: {} },
    transformation_summary: { version: 1, transformations: [] },
    execution_context: { cwd: "/project", shell: { path: "/bin/bash", args: [], identityDigest: hash },
      backend: "native", environmentDigest: hash, targetFingerprint: hash },
    effects: [{ effectId: "effect-1", kind: "read", target: "/project", parameters: ["pwd"],
      cwdCategory: "repo-root", risk: "low" }], native_constraints: [{ source: "tool-default", policy: "prompt" }],
    authorization_evidence: [{ messageId: "user-1", text: "Read current directory" }],
    verified_user_message_ids: new Set(["user-1"]), context_complete: true, redaction_complete: true,
    restriction_state: "unknown", mode: "smart", policy_version: hash,
    reviewer: { provider: "fixture", model: "cheap" }, reviewer_source: "explicit-profile",
    fallback: { provider: "local", model: "lfm2.5-230m", installedOnly: true }, ...overrides };
}
export function prepared(overrides: Partial<ReviewBuildInput> = {}, clock: () => number = () => 0) {
  return buildReviewRequest(input(overrides), clock);
}
export function askReply() {
  return { status: "ok" as const, text: JSON.stringify({ decision: "ask", risk: "unknown",
    authorization: "unknown", effects: ["effect-1"], unknowns: ["ambiguous-authorization"],
    reasonCode: "USER_CONFIRMATION_REQUIRED", evidence: { userMessageIds: [], bindings: [] } }),
    outputTokens: 40, toolCalls: [] };
}
export class FakeClock implements ReviewClock {
  time = 0;
  timers = new Set<{ at: number; callback: () => void }>();
  now = () => this.time;
  timer = (callback: () => void, milliseconds: number) => {
    const timer = { at: this.time + milliseconds, callback }; this.timers.add(timer);
    return () => { this.timers.delete(timer); };
  };
  advance(milliseconds: number) {
    this.time += milliseconds;
    for (const timer of this.timers) if (timer.at <= this.time) {
      this.timers.delete(timer); timer.callback();
    }
  }
}
