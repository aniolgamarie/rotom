export function pluginModelMethod(capability: string, method: "complete" | "completeSimple" | "stream" | "streamSimple"): (...args: any[]) => any;
export function ownedCompactionHook(handler: (...args: any[]) => any): (...args: any[]) => Promise<any>;

export function selectedPluginModel(capability: string, reference: string | undefined, currentModel: any): any;
export function selectedPluginModels(capability: string): any[];
