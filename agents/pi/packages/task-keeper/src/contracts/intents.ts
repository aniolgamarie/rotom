import type { OwnerIdentity } from "./ownership.ts";

/** Only a committed, never-dispatched intent for this epoch can enter dispatch. */
export function intentDispatchable(owner: OwnerIdentity, intent: { scopeId: string; epoch: number; status: string } | null): boolean {
  return intent !== null && intent.scopeId === owner.scopeId && intent.epoch === owner.epoch && intent.status === "prepared";
}
