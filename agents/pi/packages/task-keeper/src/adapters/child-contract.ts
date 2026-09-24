import type { Owner } from "../store/database.ts";
import type { ProcessIdentity } from "./process-identity.ts";
import { originalProcessStopped } from "./process-identity.ts";

export interface ChildDescriptor {
  id: string; nonce: string; owner: Owner; parentProcess: ProcessIdentity;
  jobId: string; analyticsTaskId?:string; stepId: string; cwd: string; storePath: string;
  provider: string; model: string; thinking: string; readOnly: boolean;
  modelDigest: string;
  runtimeDigest: string;
  routeId: string; sourceCwd: string; policyDigest: string;
  timeoutMs: number; maxModelTurns: number;
  expiresAt: number; maxChildren: number; maxReaders: number;
  protected: boolean;
  budgetLimits: Array<{ id: string; ceiling: number; minimumRemaining?: number }>;
  allowedArtifacts: Array<{ id: string; snapshot: string }>;
}
export interface ChildObservation {
  ready: boolean; descriptorId: string; process: ProcessIdentity | null;
  producerId: string; leaseId: string;
  cwd: string; provider: string; model: string; thinking: string;
  modelDigest: string;
  runtimeDigest?: string;
  settled: boolean; activeTools: string[]; stopReason: string | null;
  externalWork?: string[];
  toolErrors: Array<{ toolCallId: string; toolName: string; error: string }>;
  requestGate: boolean; requestDenials: string[];
  lastResponse: { status: number; headers: Record<string, string>; errorBody?: string } | null;
  lastError: string | null;
  lastRequestTimeout?: {requestId:string;at:number}|null;
  fileReads: Array<{ path: string; firstLine: number; lastLine: number } & ReadDelivery>;
  artifactReads: Array<{ id: string; start: number; end: number; total: number } & ReadDelivery>;
  structuredOutputs?: Array<{ toolCallId: string; requestOrdinal: number; valueDigest: string }>;
  contextOperations?: Array<{ id: string; reason: string; status: "running" | "completed" | "failed"; error?: string }>;
  usageIds?: string[];
  sequence: number;
}

export interface ReadDelivery {
  toolCallId?: string;
  payloadDigest?: string;
  readRequest?: number;
  deliveredRequest?: number;
}

/** Pure release rule: native completion and lease hints cannot replace physical/external-work evidence. */
export function childTerminationConfirmed(observation: Pick<ChildObservation, "process" | "externalWork">, processStopped: boolean | null): boolean {
  return !!observation.process && processStopped === true
    && Array.isArray(observation.externalWork) && observation.externalWork.length === 0;
}

/** Older observations without explicit external-work coverage cannot release a writer. */
export function childPhysicallyStopped(observation: ChildObservation): boolean {
  return childTerminationConfirmed(observation, observation.process ? originalProcessStopped(observation.process) : null);
}
