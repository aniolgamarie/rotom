import { Type } from "typebox";

/** Public model input has no authority to select a scope, reset accounting or replace environment bindings. */
export function kernelTaskParameters() {
  return Type.Object({ action: Type.Union([Type.Literal("inspect"), Type.Literal("fix"), Type.Literal("status"), Type.Literal("usage"), Type.Literal("models"), Type.Literal("decisions"), Type.Literal("propose"), Type.Literal("pause"), Type.Literal("resume"), Type.Literal("stop")]),
    goal: Type.Optional(Type.String({ maxLength: 65536 })), jobId: Type.Optional(Type.String({ maxLength: 200 })),
    proposal: Type.Optional(Type.Object({ packetId: Type.String({ maxLength: 200 }),
      action: Type.Union([Type.Literal("advance"), Type.Literal("verify"), Type.Literal("request_finish"), Type.Literal("request_help")]),
      target: Type.String({ maxLength: 200 }), reason: Type.String({ maxLength: 2000 }),
      evidenceIds: Type.Array(Type.String({ maxLength: 200 }), { maxItems: 128 }) }, { additionalProperties: false })) }, { additionalProperties: false });
}
