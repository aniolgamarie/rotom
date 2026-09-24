import type { Api, Model } from "@earendil-works/pi-ai/compat";
export function webSearchModel(purpose: string): Model<Api> | undefined;
export function webSearchAuthAvailable(purpose: string): boolean;
export function webSearchAuth(purpose: string, signal?: AbortSignal): Promise<{ model: Model<Api>; apiKey: string; headers: Record<string, string | null> } | undefined>;
