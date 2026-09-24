import type { Api, Model } from "@earendil-works/pi-ai/compat";
export function webModels(): Model<Api>[];
export function webModel(purpose: string, reference?: string, currentModel?: Model<Api>): Model<Api>;
export function webComplete(model: Model<Api>, context: any, options?: any): Promise<any>;
