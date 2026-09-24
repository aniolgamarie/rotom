/** Pure timing decision. Eligibility, ownership, resources and I/O remain in the controller. */
export interface RecoveryTiming {
  now: number; monotonic: number; previousWall: number; previousMonotonic: number;
  notBefore: number; sharedNotBefore: number; deadlineAt: number | null | undefined;
}
export function recoveryTiming(input: RecoveryTiming): { action: "deadline" | "wait" | "ready"; notBefore: number } {
  if (input.deadlineAt != null && input.now >= input.deadlineAt) return { action: "deadline", notBefore: input.notBefore };
  const expectedWall = input.previousWall + Math.max(0, input.monotonic - input.previousMonotonic);
  const rollback = Math.max(0, Math.floor(expectedWall - input.now));
  const notBefore = Math.max(input.notBefore + rollback, input.sharedNotBefore);
  return { action: input.now < notBefore ? "wait" : "ready", notBefore };
}
