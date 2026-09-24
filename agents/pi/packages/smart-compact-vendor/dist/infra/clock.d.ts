/**
 * Clock abstraction.
 *
 * Most callers want `Date.now()` directly, but `runSmartCompact` and the
 * pendingRef lifecycle compare timestamps in tight windows (TTL, timeouts,
 * cache freshness). Routing every `Date.now()` through a Clock makes those
 * paths deterministic in tests and reusable across services.
 */
export interface Clock {
    now(): number;
}
export declare const systemClock: Clock;
//# sourceMappingURL=clock.d.ts.map