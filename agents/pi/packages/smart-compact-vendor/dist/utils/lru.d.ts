/**
 * Tiny `Map`-backed LRU helpers.
 *
 * We use `Map`'s insertion-order guarantee instead of pulling in a separate
 * dependency: re-inserting a key on access moves it to the "newest" tail,
 * and `keys().next().value` is always the oldest. Each operation is O(1)
 * amortized.
 *
 * Why an explicit module instead of inline helpers in `session-log.ts`:
 *   1. Pure, host-independent functions — trivially unit-testable.
 *   2. Reusable: any future bounded-cache (e.g. a tokenizer or fingerprint
 *      cache) can pick this up without re-implementing the eviction loop.
 *   3. The narrow contract is documented in one place rather than buried
 *      next to its first consumer.
 */
/**
 * Get a value and promote it to the most-recent slot in the LRU order.
 * Returns `undefined` when the key is absent.
 *
 * Gating on `has()` (not on `value !== undefined`) is critical: it lets us
 * cache value types that legitimately include `undefined` without
 * silently skipping LRU promotion. The previous shape had this latent bug.
 */
export declare function lruGet<K, V>(m: Map<K, V>, key: K): V | undefined;
/**
 * Insert or overwrite a value, place it at the most-recent slot, and evict
 * older entries until size ≤ max. `max` must be ≥ 1 — callers are expected
 * to validate (a non-positive cap would empty the cache on every write).
 */
export declare function lruSet<K, V>(m: Map<K, V>, key: K, value: V, max: number): void;
//# sourceMappingURL=lru.d.ts.map