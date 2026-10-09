# Cursor K3 历史与自动备用链（2026-10-09）

官方 OMP v18.8.6 / `f068751e2f1dbdbc195977776d47a26db8697495` 的 Cursor K3 历史校验只允许同一 Cursor 型号的 assistant 历史。`packages/ai/src/providers/cursor.ts` 的 `assertCursorKimiK3HistoryReplayable`（约 5698–5735 行）检查每条 assistant 的 API、provider 和 model；异型号会报 `cannot continue history from a different model`，要求新会话。该循环未排除 error/aborted assistant，因此失败的跨型号备用尝试也可能让后续 K3 请求失败。同型号缺 thinking blocks 只警告；它与异型号硬拒绝是不同情况。

仓库仅修正 `omp-kernel` 的默认自动执行备用链：K3 high/max、GLM 5.2 high/max 与 Grok 4.7 high 的五条链设为 `[]`，另添加无档位 `cursor/kimi-k3 = []`。Composer 2.5 low/medium 到 Kimi 2.7 Code 的两条链保留；basic、TF、DeepSeek 模型池、角色套件及权限主审/远程/本地兜底均保持原配置。没有修改上游、插件或机器私人配置，也没有删除或改写会话历史。

空数组具有明确含义，不能用删除键代替。官方 `packages/coding-agent/src/session/retry-fallback-chains.ts` 中 `resolveRetryFallbackChainKey` 优先选具体模型/档位，随后选无档位模型键，再选 wildcard、角色与 default；选择模型键时不会跳过空数组。`getRetryFallbackEffectiveChain` 对空链只保留主模型，`findRetryFallbackCandidates` 在链长度不超过一时返回无候选，不会转而使用角色或 default。无档位模型键适用于同模型的任意思考档位。

配置修正只能防止默认自动跨型号路线继续触发此问题。用户手动将 K3 与其他型号用于同一会话，或私人覆盖重新启用跨型号备用链，仍受上游历史限制。已有混合历史应保留原会话，并另开新会话使用 K3；受管配置回滚不改变这项上游限制，也不会修复已混合的历史。本次验证使用离线配置解析、原生渲染与锁闭包测试，未启动宿主或请求真实模型。
