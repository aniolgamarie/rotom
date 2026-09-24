// 请求账本是真实计量来源；统计重新分组只改 UsageLink，不改变预算记录。
import { UsageLedger, type UsageFact } from "./ledger.ts";
import { digest } from "../contracts/primitives.ts";
import type { Store } from "../store/database.ts";

export function importManagedUsage(store: Store, taskId: string, descriptor: any) {
  const job = store.get<any>("managed-jobs", taskId), budget = store.get<any>("agentcfg-request-ledger-v1", taskId);
  if (!job || !budget) return;
  const ledger = new UsageLedger(store), usageTask = job.analyticsTaskId ?? taskId;
  if (!ledger.hasTask(usageTask)) ledger.begin({ id: usageTask, sessionId: job.parentSessionId ?? job.workScope,
    title: job.goal, workflow: job.workflow, comparisonGroup: job.options?.comparisonGroup ?? null }, job.createdAt);
  for (const book of Object.values(budget.state.request_budgets ?? {}) as any[]) for (const request of Object.values(book.requests) as any[]) {
    if (request.attempt_id !== descriptor.attempt_id) continue;
    const generationId = "managed-" + request.request_id;
    const observed = request.settled_usage;
    const old = store.get<UsageFact>("usage-generations", generationId);
    const sourceDigest = digest(request);
    if (store.get<any>("managed-usage-imports", generationId)?.source_digest === sourceDigest) continue;
    const fact: UsageFact = { id: "usage-" + sourceDigest, revision: old ? old.revision + 1 : 1, supersedes: old?.id ?? null,
      generationId, provider: descriptor.provider_id, model: descriptor.model_id, modelVersion: descriptor.model_digest,
      role: descriptor.role_id, source: "agentcfg-request-reservation-v1", startedAt: request.reserved_at,
      endedAt: request.settled_at ?? request.sent_at ?? request.reserved_at,
      tokens: { input: observed?.input_tokens ?? null, output: observed?.output_tokens ?? null, cacheRead: null, cacheWrite: null },
      attemptIds: [request.request_id], coverage: observed ? "aggregate" : "unknown",
      outcome: request.state === "settled" && !request.never_sent ? "success" : "unknown",
      rawUsage: { buckets: { input: observed?.input_tokens ?? null, output: observed?.output_tokens ?? null, cacheRead: null, cacheWrite: null },
        totalTokens: observed?.input_tokens !== null && observed?.output_tokens !== null && observed ? observed.input_tokens + observed.output_tokens : null,
        normalization: "openai-total-input-cache-breakdown-unavailable" },
      cost: { kind: "unknown", amount: null, currency: null, source: "provider-cost-unavailable", quoteId: null } };
    if (request.never_sent) {
      store.put("usage-send-proofs", request.request_id, { generationId });
      fact.notSent = true; fact.notSentProofs = [request.request_id];
      fact.tokens = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };
      fact.cost = { kind: "actual", amount: "0", currency: null, source: "verified-not-sent", quoteId: null };
      fact.coverage = "complete";
    }
    store.transaction(() => {
      ledger.record(fact, usageTask);
      store.put("managed-usage-imports", generationId, { schema_version: 1, source_digest: sourceDigest });
    });
  }
}
