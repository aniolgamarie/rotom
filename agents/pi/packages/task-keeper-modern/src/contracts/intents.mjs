export function intentDispatchable(owner, intent) {
    return intent !== null && intent.scopeId === owner.scopeId && intent.epoch === owner.epoch && intent.status === "prepared";
}
