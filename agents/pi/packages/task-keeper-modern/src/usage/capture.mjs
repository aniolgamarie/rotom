import { priceUsage } from "./pricing.mjs";
import { UsageLedger, sdkUsage } from "./ledger.mjs";
import { newId, digest } from "../contracts/primitives.mjs";
export class UsageCapture {
    ledger;
    store;
    lastGeneration = null;
    active = null;
    constructor(store){
        this.store = store;
        this.ledger = new UsageLedger(store);
    }
    begin(input, enabled, now = Date.now()) {
        if (this.active) this.end(undefined, "unknown", now);
        if (!enabled) {
            const taskId = input.taskId ?? this.ledger.activeTask(input.sessionId)?.id;
            if (taskId && this.ledger.hasTask(taskId)) this.ledger.gap(taskId, "usage-disabled");
            return;
        }
        if (input.taskId && !this.ledger.hasTask(input.taskId)) {
            const job = this.store.get("managed-jobs", input.taskId);
            if (job) {
                this.ledger.begin({
                    id: input.taskId,
                    sessionId: job.parentSessionId,
                    title: job.goal,
                    workflow: job.workflow,
                    comparisonGroup: job.options?.comparisonGroup ?? null
                }, job.createdAt);
                this.ledger.gap(input.taskId, "usage-history-unavailable-at-enable");
            }
        }
        const task = input.taskId ? this.ledger.task(input.taskId) : this.ledger.current(input.sessionId, now);
        const id = newId("generation"), pending = sdkUsage({
            generationId: id,
            provider: input.provider,
            model: input.model,
            modelVersion: input.modelVersion ?? null,
            accountPlanRef: input.accountPlanRef ?? null,
            role: input.role,
            startedAt: now,
            endedAt: now,
            usage: undefined,
            attemptIds: [],
            outcome: "unknown",
            source: "runtime-generation-start"
        });
        this.ledger.record(pending, task.id);
        this.active = {
            id,
            taskId: task.id,
            startedAt: now,
            provider: input.provider,
            model: input.model,
            modelVersion: input.modelVersion ?? null,
            accountPlanRef: input.accountPlanRef ?? null,
            role: input.role,
            attemptIds: [],
            quotes: structuredClone(input.quotes ?? []),
            last: pending,
            responses: {},
            zeroReported: new Set()
        };
    }
    tool(id, failed) {
        const link = this.active ? {
            taskId: this.active.taskId,
            generationId: this.active.id
        } : this.lastGeneration;
        if (!link) return;
        const key = digest([
            id,
            link.generationId
        ]);
        const old = this.store.get("usage-tools", key);
        if (old && failed === null) return;
        this.store.put("usage-tools", key, {
            id,
            ...old ?? link,
            failed,
            at: Date.now()
        });
    }
    notSent(id) {
        if (!this.active) return;
        this.attempt(id);
        this.store.put("usage-send-proofs", id, {
            generationId: this.active.id,
            id,
            source: "transport-invocation-not-performed",
            at: Date.now()
        });
    }
    metering(id, zero) {
        if (!this.active) return;
        if (zero) this.active.zeroReported.add(id);
        else this.active.zeroReported.delete(id);
    }
    response(id, status) {
        if (this.active) this.active.responses[id] = status;
    }
    hasActive() {
        return this.active !== null;
    }
    attempt(id) {
        if (!this.active || this.active.attemptIds.includes(id)) return;
        const active = this.active;
        active.attemptIds.push(id);
        const next = {
            ...active.last,
            id: newId("usage-pending"),
            revision: active.last.revision + 1,
            supersedes: active.last.id,
            attemptIds: [
                ...active.attemptIds
            ],
            source: "runtime-request-observation"
        };
        this.ledger.record(next, active.taskId);
        active.last = next;
    }
    end(usage, outcome, now = Date.now(), scope = "generation") {
        const active = this.active;
        if (!active) return null;
        this.active = null;
        const fact = sdkUsage({
            generationId: active.id,
            provider: active.provider,
            model: active.model,
            modelVersion: active.modelVersion ?? null,
            accountPlanRef: active.accountPlanRef ?? null,
            role: active.role,
            startedAt: active.startedAt,
            endedAt: now,
            usage,
            outcome,
            attemptIds: active.attemptIds,
            source: "native-SDK-generation"
        });
        if (active.attemptIds.length > 0 && active.attemptIds.every((id)=>active.zeroReported.has(id))) {
            fact.tokens = {
                input: 0,
                output: 0,
                cacheRead: 0,
                cacheWrite: 0
            };
            fact.coverage = "aggregate";
        }
        if (scope === "operation-aggregate") {
            fact.source = "native-operation-aggregate";
            if (fact.coverage !== "unknown" && active.attemptIds.length > 0 && active.attemptIds.every((id)=>active.responses[id] >= 200 && active.responses[id] < 400)) fact.coverage = "aggregate";
        }
        fact.revision = active.last.revision + 1;
        fact.supersedes = active.last.id;
        fact.id = newId("usage-terminal");
        if (active.quotes.length) fact.cost = priceUsage(fact, active.quotes);
        fact.notSentProofs = active.attemptIds.filter((id)=>this.store.get("usage-send-proofs", id)?.generationId === active.id);
        if (active.attemptIds.length > 0 && fact.notSentProofs.length === active.attemptIds.length) {
            fact.notSent = true;
            fact.notSentProofs = [
                ...active.attemptIds
            ];
            fact.tokens = {
                input: 0,
                output: 0,
                cacheRead: 0,
                cacheWrite: 0
            };
            fact.coverage = "complete";
            fact.cost = {
                kind: "actual",
                amount: "0",
                currency: null,
                source: "verified-not-sent",
                quoteId: null
            };
        }
        this.ledger.record(fact, active.taskId);
        this.lastGeneration = {
            taskId: active.taskId,
            generationId: active.id
        };
        if (fact.coverage === "unknown") this.ledger.gap(active.taskId, "unobserved-generation-usage");
        return fact;
    }
}
export function observeUsage(store, body) {
    try {
        body();
    } catch (error) {
        try {
            store?.put("usage-capture-errors", newId("usage-gap"), {
                code: typeof error?.code === "string" ? error.code : "USAGE_CAPTURE_FAILED",
                at: Date.now()
            });
        } catch  {}
    }
}
