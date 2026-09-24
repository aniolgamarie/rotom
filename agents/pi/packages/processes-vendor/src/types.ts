export type ProcessStatus =
  | "queued"
  | "running"
  | "terminating"
  | "terminate_timeout"
  | "exited"
  | "killed";

export const LIVE_STATUSES: ReadonlySet<ProcessStatus> = new Set([
  "queued",
  "running",
  "terminating",
  "terminate_timeout",
]);

export type ProcessEndReason =
  | "exit"
  | "signal"
  | "spawn_error"
  | "missing_pid"
  | "kill_timeout"
  | "lost";

export interface ProcessSignalInfo {
  name: NodeJS.Signals;
  number: number | null;
  description: string;
}

export interface ProcessInfo {
  id: string;
  name: string;
  pid: number; // 监督者登记的scope leader；排队时为-1，不能据此对裸PID/PGID发信号。
  command: string;
  cwd: string;
  startTime: number;
  endTime: number | null;
  status: ProcessStatus;
  exitCode: number | null;
  success: boolean | null; // null if running, true if exit code 0, false otherwise
  stdoutFile: string;
  stderrFile: string;
  endReason: ProcessEndReason | null;
  signal: ProcessSignalInfo | null;
  errorMessage: string | null;
}

export type ManagerEvent =
  | { type: "process_started"; info: ProcessInfo }
  | { type: "process_ended"; info: ProcessInfo }
  | {
      type: "process_output_changed";
      id: string;
      appendedText?: Array<{ type: "stdout" | "stderr"; text: string }>;
      droppedLines?: number;
    }
  | { type: "processes_changed" };

export type KillResult =
  | { ok: true; info: ProcessInfo }
  | { ok: false; info: ProcessInfo; reason: "not_found" | "timeout" | "error" };

export type WriteResult =
  | { ok: true }
  | {
      ok: false;
      reason: "not_found" | "process_exited" | "stdin_closed" | "write_error";
    };
