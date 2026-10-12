// 现代来源入口只提供状态说明；受管工具由本会话自有factory注册，不能另创sender。
export default function modelDelegateSource(pi) {
  pi.registerCommand("delegate-capability", { description: "Show selected strict delegation boundary", async handler(_args, ctx) {
    ctx.ui.notify("统一委派候选：严格输入token上界未qualified时不可发送；查询与取消沿原controller。", "info");
  } });
}
