import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { createJiti } from "jiti";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/** Inject a backend ToolResult fault, then use the pinned backend's real public-result projection. */
export default async function detailsError(pi: ExtensionAPI) {
  const { toSubagentDelegationResponse } = await createJiti(import.meta.url).import<any>(fileURLToPath(new URL("../../node_modules/pi-subagents/src/slash/delegation-adapters.ts", import.meta.url)));
  const requests = new Map<string, any>();
  pi.events.on("prompt-template:subagent:request", (value: any) => requests.set(value.requestId, value));
  pi.events.on("prompt-template:subagent:response", (response: any) => {
    const request = requests.get(response.requestId);
    if (!request || request.nodeId !== "implement" || response.status !== "completed") return;
    const interrupted = process.env.TASK_KEEPER_FIXTURE_NATIVE_FAULT === "interrupted";
    const bridge = { content: [{ type: "text", text: "Done" }], details: { runId: response.runId,
      results: [{ agent: response.agent, model: response.model, thinking: response.thinking, exitCode: 0, finalOutput: "Done",
        ...(interrupted ? { interrupted: true } : { error: "FIXTURE_REQUIRED_DETAILS_ERROR" }) }] } };
    const converted = toSubagentDelegationResponse(request, bridge, false);
    const config = JSON.parse(readFileSync(process.env.PI_TASK_KEEPER_CONFIG!, "utf8"));
    writeFileSync(join(dirname(config.storage.path), interrupted ? "interrupted-zero.json" : "details-only-error.json"), JSON.stringify({ bridge, converted, nativeBefore: response }), { mode: 0o600 });
    delete response.result; Object.assign(response, converted);
  });
}
