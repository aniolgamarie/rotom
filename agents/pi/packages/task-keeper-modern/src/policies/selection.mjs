import { routeReference } from "./opinion.mjs";
import { windowContains } from "./calendar.mjs";
import { digest } from "../contracts/primitives.mjs";
import { decimal } from "../usage/ledger.mjs";
export function selectModel(config, input) {
    const policy = config.modelPolicy, rejected = [], assessed = [];
    const result = (selected, reason, sampleIds = [], quoteIds = [])=>({
            selected,
            reason,
            rejected,
            evaluatedAt: input.at,
            policyVersion: digest(policy),
            sampleIds: [
                ...new Set([
                    ...sampleIds,
                    ...assessed.flatMap((row)=>row.sampleIds)
                ])
            ].sort(),
            quoteIds: [
                ...new Set([
                    ...quoteIds,
                    ...assessed.flatMap((row)=>row.quoteIds)
                ])
            ].sort(),
            assessed,
            comparisonKey: input.comparisonKey ?? null,
            referenceInputBand: input.referenceInputBand ?? null,
            historyRange: input.historyRange ?? null
        });
    if (!input.automatic) {
        if (!input.manual) return result(null, "manual-model-required");
        const reasons = Object.hasOwn(input.eligible, input.manual) ? input.eligible[input.manual] : [
            "not-authorized"
        ];
        if (reasons.length) {
            rejected.push({
                id: input.manual,
                reasons
            });
            return result(null, "manual-model-ineligible");
        }
        return result(input.manual, "manual-selection");
    }
    const refs = policy.candidates.map((ref)=>routeReference(config, ref)), allowed = new Set(refs);
    const rule = policy.preferByTime.map((row, index)=>({
            ...row,
            index
        })).sort((a, b)=>b.priority - a.priority || a.index - b.index).find((row)=>windowContains(row.window, input.at, config.timePolicy.timezone));
    const preferred = (rule?.orderedCandidates ?? policy.defaultPreference).map((ref)=>routeReference(config, ref));
    let order = [
        ...new Set([
            ...preferred,
            ...refs
        ])
    ].filter((id)=>allowed.has(id));
    order = order.filter((id)=>{
        const reasons = Object.hasOwn(input.eligible, id) ? input.eligible[id] : [
            "not-authorized"
        ];
        if (reasons.length) {
            rejected.push({
                id,
                reasons
            });
            return false;
        }
        return true;
    });
    if (!order.length) return result(null, "no-eligible-authorized-model");
    if (policy.ranking !== "history-cost") return result(order[0], rule ? `time-preference:${rule.index}` : "configured-order");
    const eligible = [], unknown = [];
    for (const id of order){
        const route = config.routes[id], history = input.history?.find((row)=>row.model === `${route.provider}/${route.model}` && row.key === input.comparisonKey && row.modelVersion !== null && row.modelVersion === input.modelVersions?.[id]);
        if (history) assessed.push({
            id,
            sampleIds: history.terminalSampleIds,
            quoteIds: history.quoteIds,
            costPerAccepted: history.costPerAccepted,
            currency: history.currency,
            successRate: history.successRate
        });
        if (history && history.qualityKnownTasks >= policy.history.minimumVerifiedTasks && history.maximumPossibleSuccessRate !== null && history.maximumPossibleSuccessRate < policy.history.minimumSuccessRate) {
            rejected.push({
                id,
                reasons: [
                    "below-minimum-success-rate"
                ]
            });
            continue;
        }
        if (!history?.comparable || history.verified < policy.history.minimumVerifiedTasks || history.costPerAccepted === null) {
            unknown.push(id);
            continue;
        }
        eligible.push({
            id,
            cost: decimal(history.costPerAccepted),
            sampleIds: history.terminalSampleIds,
            quoteIds: history.quoteIds,
            currency: history.currency
        });
    }
    if (!unknown.length && !eligible.length) return result(null, "all-models-below-quality-floor");
    if (unknown.length || new Set(eligible.map((row)=>row.currency)).size !== 1) {
        const remaining = new Set([
            ...unknown,
            ...eligible.map((row)=>row.id)
        ]);
        return result(order.find((id)=>remaining.has(id)) ?? null, "history-insufficient-configured-order");
    }
    eligible.sort((a, b)=>a.cost < b.cost ? -1 : a.cost > b.cost ? 1 : order.indexOf(a.id) - order.indexOf(b.id));
    return eligible.length ? result(eligible[0].id, "history-cost", eligible[0].sampleIds, eligible[0].quoteIds) : result(null, "all-models-below-quality-floor");
}
