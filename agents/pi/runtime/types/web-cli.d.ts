export function webYouTubeInfo(videoId: string): Promise<{ streamUrl: string; duration: number | null }>;
export function webRemoteFrame(url: string, seconds: number): Promise<{ data: string; mimeType: string }>;
export function webGitClone(owner: string, repo: string, ref?: string): Promise<string>;
export function webGitContent(directory: string, type: "root" | "tree" | "blob", path?: string): Promise<string>;
