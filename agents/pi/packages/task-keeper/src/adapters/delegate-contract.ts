import type { ChildObservation } from "./child-contract.ts";
import type { EvidenceOrigin } from "../evidence/records.ts";

export interface DelegationResult {
  descriptorId: string; nativeRunId: string | null; status: "ended" | "failed" | "unknown";
  nativeStatus?: string | null; nativeExitCode?: number | null;
  modelIdentity?: { requested: { provider: string; model: string }; runtimeObservationSource: "client_configuration";
    responseModel: null; serverWeights: "unverified" };
  terminationConfirmed: boolean; content: unknown; error: string | null; observations: ChildObservation[];
  parentHelperDenials?: string[]; notSent?: boolean;
  evidenceOrigin?: EvidenceOrigin | null;
  invocationWindow?: { startedAt: number; endedAt: number } | null;
  evidence?: {schema_version:1;physical_run_id:string;attempt_id:string;lease_id:string;grant_generation:number;
    process_identity_digest:string;termination_evidence_digest:string;terminated:boolean;resources_reclaimed:boolean;exit_code:number|null} | null;
}
