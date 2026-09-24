import { ContractError } from "../contracts/primitives.ts";
import type { Receipt } from "../contracts/task.ts";

export interface Progress {
  jobId: string; ownerEpoch: number; nativeStatus: string; taskStatus: Receipt["status"];
  phase: string; sequences: Record<string, number>; stale: boolean; lateEvents: number;
}
export interface ProgressEvent { jobId: string; ownerEpoch: number; producer: string; seq: number; nativeStatus: string; phase: string }

export function projectProgress(previous: Progress, event: ProgressEvent, receipt: Receipt): Progress {
  if (receipt.jobId !== previous.jobId) throw new ContractError("RECEIPT_SCOPE_MISMATCH");
  const result = { ...previous, sequences: { ...previous.sequences }, taskStatus: receipt.status };
  if (event.jobId !== previous.jobId || event.ownerEpoch !== previous.ownerEpoch) {
    result.lateEvents++; return result;
  }
  const prior = previous.sequences[event.producer] ?? 0;
  if (event.seq <= prior) return result;
  result.sequences[event.producer] = event.seq;
  if (event.seq !== prior + 1) result.stale = true;
  result.nativeStatus = event.nativeStatus; result.phase = event.phase;
  return result;
}
