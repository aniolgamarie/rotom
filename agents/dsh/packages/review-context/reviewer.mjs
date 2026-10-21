// 只挂载于审批 preset；公开限制作用于当前 agent，不能挂在宿主根 scope。
export const name = "rotom-reviewer-tool-restriction";
export const inject = ["tools"];

export function apply(ctx) {
  ctx.get("tools").restrict({ allow: ["rotom_review_context"] });
}
