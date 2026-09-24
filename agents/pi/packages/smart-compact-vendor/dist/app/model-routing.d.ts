import type { Api, Model } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { CompactConfig } from "../types.ts";
/** Resolve a provider/id string through the host model registry. */
export declare function findModelById(ctx: ExtensionContext, modelId: string): Model<Api> | undefined;
/** Resolve per-stage routes while preserving explicit user model precedence. */
export declare function resolveModels(ctx: ExtensionContext, primary: Model<Api> | undefined, config: CompactConfig, explicit?: boolean): {
    segModel: Model<Api> | undefined;
    sumModel: Model<Api> | undefined;
    verifyModel: Model<Api> | undefined;
};
//# sourceMappingURL=model-routing.d.ts.map