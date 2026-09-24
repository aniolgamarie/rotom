import { Store, type Owner } from "../store/database.ts";
import { ContractError, digest } from "../contracts/primitives.ts";
import { authorizeProposal, recheck, type Packet, type StepContract } from "./packet.ts";

/** Durable proposal admission; fixed workflows retain sole dispatch authority. */
export class DecisionLedger {
  private store: Store;
  private owner: Owner;
  constructor(store: Store, owner: Owner) { this.store = store; this.owner = owner; }
  authorize(input: unknown, packet: Packet, allowedTargets: string[], commit?: (contract: StepContract) => void): StepContract {
    return this.store.transaction(() => {
      this.store.assertOwner(this.owner);
      if (packet.ownerEpoch !== this.owner.epoch) throw new ContractError("STALE_PROPOSAL");
      const seen = new Set(this.store.list<StepContract>("proposals").map((entry) => entry.id));
      const contract = authorizeProposal(input, packet, allowedTargets, seen);
      this.store.put("proposals", contract.fingerprint, contract); commit?.(contract); return contract;
    });
  }
  check(contract: StepContract, current: Packet, resourceAllowed = true): void {
    this.store.assertOwner(this.owner);
    const stored = this.store.get<StepContract>("proposals", contract.fingerprint);
    if (!stored || digest(stored) !== digest(contract)) throw new ContractError("PROPOSAL_NOT_REGISTERED");
    recheck(stored, current, resourceAllowed, false);
    if (current.ownerEpoch !== this.owner.epoch) throw new ContractError("STALE_PROPOSAL");
  }
  admit(contract: StepContract, current: Packet, resources: Array<{ id: string; capacity: number; units: number }>, allowed: () => boolean) {
    return this.store.prepare(this.owner, `proposal-${contract.fingerprint}`, "proposal", { contract }, resources, () => {
      const stored = this.store.get<StepContract>("proposals", contract.fingerprint);
      if (!stored || digest(stored) !== digest(contract)) throw new ContractError("PROPOSAL_NOT_REGISTERED");
      recheck(stored, current, allowed(), false);
      if (current.ownerEpoch !== this.owner.epoch) throw new ContractError("STALE_PROPOSAL");
    });
  }
}
