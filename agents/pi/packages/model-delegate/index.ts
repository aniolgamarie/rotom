import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { isProtocolError, reject } from "@agentcfg/pi-runtime/managed-types";
import { loginCodex } from "@agentcfg/pi-runtime/user-login";
import { DelegateRunner } from "./runner.ts";

const choices = (values: string[]) => Type.Union(values.map(value => Type.Literal(value)));
export default function modelDelegate(pi: ExtensionAPI) {
  const runtime = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!runtime || runtime.owner?.role !== "manager") reject("CAPABILITY_MISSING", 5);
  const runner = new DelegateRunner(pi, runtime);
  if (!runtime.manifest.bootstrap) pi.registerTool({ name: "model_delegate", label: "Model Delegate", description: "Run one bounded readonly review or investigation through the selected backend. Execution evidence is separate from task acceptance.",
    parameters: Type.Object({ backend: Type.Optional(choices(["pi", "codex"])), mode: choices(["review", "investigate"]),
      preset: choices(["general", "context", "challenge", "plan", "research", "review", "scout"]),
      task: Type.String({ minLength: 1, maxLength: 65536 }), cwd: Type.String({ minLength: 1 }),
      model_role: Type.Optional(Type.String({ minLength: 1 })), model: Type.Optional(Type.String({ minLength: 1 })),
      timeout_seconds: Type.Integer({ minimum: 1 }), context_artifact: Type.Optional(Type.String({ minLength: 1, maxLength: 200 })) }, { additionalProperties: false }),
    async execute(id, params, signal, onUpdate) {
      try {
        const result = await runner.execute(id, params, signal, progress => onUpdate?.({ content: [{ type: "text", text: JSON.stringify(progress) }], details: progress }));
        return { content: [{ type: "text", text: JSON.stringify(result) }], details: result, isError: result.state !== "completed" };
      } catch (error) {
        const result = { error_code: isProtocolError(error) ? error.code : "DELEGATE_OPERATION_FAILED", exit_code: isProtocolError(error) ? error.exitCode : 6 };
        return { content: [{ type: "text", text: JSON.stringify(result) }], details: result, isError: true };
      }
    },
  });
  pi.registerCommand("model-login", { description: "Log in to the selected instance's Codex CLI", async handler(args, ctx) {
    if (args.trim() !== "codex") { ctx.ui.notify("用法：/model-login codex", "error"); return; }
    try { const result = await loginCodex(runtime, pi, ctx); ctx.ui.notify(result.state === "ended" ? "Codex 登录命令已结束；模型调用仍需单独验证。" : "Codex 登录已取消。", result.state === "ended" ? "info" : "warning"); }
    catch (error) { ctx.ui.notify("Codex 登录未完成" + (isProtocolError(error) ? "（" + error.code + "）" : "") + "；请检查配置准入、所选运行包、网络路线及监督状态。", "error"); }
  } });
}
