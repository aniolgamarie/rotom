import { digest } from "./primitives.mjs";
export function classifyEventAppend(event, matches) {
    const hash = digest(event);
    if (!matches.length) return {
        status: "inserted",
        hash,
        conflictScopes: []
    };
    if (matches.length === 1 && matches[0].hash === hash) return {
        status: "duplicate",
        hash,
        conflictScopes: []
    };
    return {
        status: "conflict",
        hash,
        conflictScopes: [
            ...new Set([
                event.scopeId,
                ...matches.map((match)=>match.scopeId)
            ])
        ]
    };
}
export function eventSequenceGaps(events) {
    const next = new Map(), gaps = [];
    for (const event of events){
        const expected = next.get(event.producer) ?? 1;
        if (expected !== event.seq) gaps.push({
            producer: event.producer,
            expected,
            actual: event.seq
        });
        next.set(event.producer, event.seq + 1);
    }
    return gaps;
}
