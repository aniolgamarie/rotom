import { digest } from "./primitives.ts";

export interface FactEvent {
  id: string; producer: string; seq: number; scopeId: string; kind: string; payload: Record<string, unknown>;
}
export interface EventIdentityMatch { hash: string; scopeId: string }

/** Candidates are the durable rows matching event ID or producer/sequence, read in the append transaction. */
export function classifyEventAppend(event: FactEvent, matches: readonly EventIdentityMatch[]): {
  status: "inserted" | "duplicate" | "conflict"; hash: string; conflictScopes: string[];
} {
  const hash = digest(event);
  if (!matches.length) return { status: "inserted", hash, conflictScopes: [] };
  if (matches.length === 1 && matches[0].hash === hash) return { status: "duplicate", hash, conflictScopes: [] };
  return { status: "conflict", hash, conflictScopes: [...new Set([event.scopeId, ...matches.map(match => match.scopeId)])] };
}

/** The store supplies unique events ordered by producer and sequence; this does not infer missing facts. */
export function eventSequenceGaps(events: readonly Pick<FactEvent, "producer" | "seq">[]): Array<{ producer: string; expected: number; actual: number }> {
  const next = new Map<string, number>(), gaps = [];
  for (const event of events) {
    const expected = next.get(event.producer) ?? 1;
    if (expected !== event.seq) gaps.push({ producer: event.producer, expected, actual: event.seq });
    next.set(event.producer, event.seq + 1);
  }
  return gaps;
}
