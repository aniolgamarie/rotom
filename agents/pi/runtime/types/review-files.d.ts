export function reviewGit(cwd: string, argv: string[]): Promise<{ code: number; stdout: string; stderr: string }>;
export function readReviewFile(path: string): Promise<Buffer>;
export function statReviewFile(path: string): Promise<{ size: number; identity: string }>;
export function runReviewEditor(path: string, line: number, cwd: string): Promise<number>;
