export interface GitStatus { status: "clean" | "dirty" | "not-repository"; changedFiles: number }
export function parseGitStatus(result: { exitCode: number; truncated: boolean; terminationConfirmed: boolean; stdout: string; stderr: string }): GitStatus;
export function inspectGitStatus(runtime: any, context: any): Promise<GitStatus>;
