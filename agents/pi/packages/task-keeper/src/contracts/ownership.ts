export interface OwnerIdentity { scopeId: string; token: string; epoch: number }

/** Authority is an exact active identity, independent of success or lease observations. */
export function ownerMatches(expected: OwnerIdentity, current: (OwnerIdentity & { active: boolean }) | null): boolean {
  return current?.active === true && current.scopeId === expected.scopeId
    && current.token === expected.token && current.epoch === expected.epoch;
}
