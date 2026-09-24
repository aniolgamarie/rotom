# 原生 usage 与国内 Coding Plan 来源复核

日期：2026-09-24。scout：gpt-5.6-luna / medium。范围：固定源码与官方公共文档只读检查，没有执行账号 usage、登录或模型请求。

## 固定 OMP registry

源码 [registry.ts](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/ai/src/usage/registry.ts) 的 `DEFAULT_USAGE_PROVIDERS` 注册 20 个 provider：alibaba-token-plan、openai-codex、kimi-code、minimax-code、muse-code、google-antigravity、google-gemini-cli、ollama、ollama-cloud、anthropic、cline-pass、zai、umans、opencode-go、github-copilot、cursor、synthetic、xai-oauth、devin、charm-hyper。

本需求关注的 openai-codex、kimi-code、zai 均在其中；不能把这三项或另一个较短的 ranking registry 当成全部 usage 支持范围。固定版没有 `zhipu-coding-plan`。

- `packages/ai/src/usage/zai.ts` 严格匹配 zai，并访问 api.z.ai 的 monitor usage 路径；不代表国内智谱 Coding Plan。
- `packages/ai/src/usage/kimi.ts` 使用 api.kimi.com 的 `/coding/v1/usages`。
- `packages/ai/src/usage/openai-codex.ts` 对应 openai-codex OAuth。
- `packages/coding-agent/src/cli/usage-cli.ts` 区分没有凭据与已登录但没有对应 usage endpoint；管理器透传，不把缺失解释成零。

## 智谱官方资料

[Coding Tool Helper](https://docs.bigmodel.cn/cn/coding-plan/extension/coding-tool-helper) 明确列出用量查询插件，并提及国内方案认证标识 `glm_coding_plan_china`。本次可见说明没有给出可核验的插件 endpoint、协议或 OMP 适配方式。

结论：可以确认官方 helper 提供用量插件，但接口及其在 OMP 中的覆盖范围未验证。此前“国内版无用量 API”的绝对结论缺乏依据，应改为“固定 OMP registry 没有对应 provider，官方插件接口未核实”。agentcfg 本次实现透明封装，不单独采集订阅用量或抓取 Cookie。

本次来源检查不证明任何真实账号、时间窗口或缓存结果成功；这些仍属于单独授权的 T064。
