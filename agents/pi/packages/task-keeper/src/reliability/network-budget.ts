/** Count one observed network/overload failure; the quota waiting duration is independent. */
export function networkFailureBudget(attempts: number, maxAttempts: number) {
  let next = attempts; next++;
  return { attempts: next, exhausted: next > maxAttempts };
}
