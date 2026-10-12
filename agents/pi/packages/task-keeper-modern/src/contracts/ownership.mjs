export function ownerMatches(expected, current) {
    return current?.active === true && current.scopeId === expected.scopeId && current.token === expected.token && current.epoch === expected.epoch;
}
