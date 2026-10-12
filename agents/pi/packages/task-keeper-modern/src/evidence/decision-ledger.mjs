import { Store } from "../store/database.mjs";
import { ContractError, digest } from "../contracts/primitives.mjs";
import { authorizeProposal, recheck } from "./packet.mjs";
export class DecisionLedger {
    store;
    owner;
    constructor(store, owner){
        this.store = store;
        this.owner = owner;
    }
    authorize(input, packet, allowedTargets, commit) {
        return this.store.transaction(()=>{
            this.store.assertOwner(this.owner);
            if (packet.ownerEpoch !== this.owner.epoch) throw new ContractError("STALE_PROPOSAL");
            const seen = new Set(this.store.list("proposals").map((entry)=>entry.id));
            const contract = authorizeProposal(input, packet, allowedTargets, seen);
            this.store.put("proposals", contract.fingerprint, contract);
            commit?.(contract);
            return contract;
        });
    }
    check(contract, current, resourceAllowed = true) {
        this.store.assertOwner(this.owner);
        const stored = this.store.get("proposals", contract.fingerprint);
        if (!stored || digest(stored) !== digest(contract)) throw new ContractError("PROPOSAL_NOT_REGISTERED");
        recheck(stored, current, resourceAllowed, false);
        if (current.ownerEpoch !== this.owner.epoch) throw new ContractError("STALE_PROPOSAL");
    }
    admit(contract, current, resources, allowed) {
        return this.store.prepare(this.owner, `proposal-${contract.fingerprint}`, "proposal", {
            contract
        }, resources, ()=>{
            const stored = this.store.get("proposals", contract.fingerprint);
            if (!stored || digest(stored) !== digest(contract)) throw new ContractError("PROPOSAL_NOT_REGISTERED");
            recheck(stored, current, allowed(), false);
            if (current.ownerEpoch !== this.owner.epoch) throw new ContractError("STALE_PROPOSAL");
        });
    }
}
