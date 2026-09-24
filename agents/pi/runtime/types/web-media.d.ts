export function webMedia(operation: "duration", path: string): Promise<number>;
export function webMedia(operation: "frame", path: string, seconds: number): Promise<{ data: string; mimeType: string }>;
