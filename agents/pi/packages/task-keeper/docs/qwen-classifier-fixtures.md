# Qwen 多服务错误夹具的来源与边界

`tests/fixtures/qwen-service-errors.json` 于 2026-09-08 核对服务官方资料后建立。模型、provider、账号与 endpoint 在测试中均为符号绑定；响应封装和数字 ID 是合成测试值，文件逐条保留来源。它不是线上流量采样，也不构成 Q3 实测认证。

Model Studio 错误文档将 `Throttling.AllocationQuota` 对应到 token 吞吐限制，因此该服务夹具映射为 `resource_pressure`；认证、上下文和未知错误分别处理，不能把所有响应都归入无限额度等待。来源：[Model Studio error codes](https://www.alibabacloud.com/help/en/model-studio/error-code)。

当前 Coding Plan FAQ 将 usage 错误解释为短期频率限制，另外区分小时、周、月额度。原 v6 的历史材料将 usage 归为资源压力；这里保留历史设计，新增当前文档对应的配置夹具，核心状态机不根据 provider 或 Qwen 名称硬编码分类。两种临时类别都不能推导为月额度耗尽；窗口类缺少可信 reset 时继续明确阻塞。来源：[Coding Plan FAQ](https://www.alibabacloud.com/help/en/model-studio/coding-plan-faq)。

SiliconFlow 文档要求按具体限流维度解释 429，并区分认证和 503/504 服务故障。测试用合成的顶层数字 code 与 RPM/TPM 消息验证另一种错误封装；不把测试数字声称为服务稳定错误码。来源：[SiliconFlow error handling](https://docs.siliconflow.cn/en/faqs/error-code)。

实际 Pi Q2 测试使用两个不同的 provider/model 绑定和响应结构，验证同一配置化恢复机制。SDK 丢失非标准字段时，HTTP observer 从最多 8 KiB、最多 250 ms 的错误响应前缀中采集脱敏详情；超限或未完成则不采用该详情，全部原始响应字节仍转发给 SDK 正常读取。成功流不进行这一读取。

有真实服务采样后应另标 `service-origin`，核对采样版本、传输、脱敏与账号绑定，不覆盖这些可重复的离线夹具，也不改变 v6 原始来源文件。

2026-09-08 追加 `tests/fixtures/qwen-observed-error.json`：从本机已有 Qwen 会话的 assistant 终态错误中提取了实际观察到的 `429 / throttling / usage allocated quota exceeded` 封装。仅保留通用错误文本、API 类型、模型家族和原记录摘要，未复制会话内容、真实模型 ID、provider 名、endpoint、账号或凭证。该样本以 `observed-native-session-terminal` 标记：它证明历史原生终态出现过此错误，不是独立 HTTP 捕获，也不证明当前插件完成过 Q3 实测。

新增 Q1 分类和 Q2 真实 Pi 回放使用这一样本；同一个错误可以通过绑定规则映射为资源压力或服务文档规定的短期频率限制，核心不按本机 provider 名分支。回放服务只在 loopback 注入错误，不对真实账号发请求。当前只找到一个有额度错误的历史绑定；这不扩大为两个真实服务均完成认证。


分类结果现保留 `evidence.categorySource`、匹配的 `ruleIndex`、`retryAfterAt`、`resetAt` 和 `uncertain`。两个服务约束同时存在时取较晚时间，并保留两个原始时间；未知错误或缺可信窗口时间的窗口错误明确不确定。旧历史记录缺此字段保持缺失，不补造来源。实际 Pi 回放另覆盖已知/未知小时窗口、认证、上下文和未知错误，核对持久历史、实际请求及被拒绝的 resume。

任务 6.1 的实现验收按 test-plan.md §6 的 Q1/Q2 边界核对：文档来源夹具和观察到的终态样本都有明确标记，多配置真实 Pi 回放通过不要求真实密钥。两个真实服务的当前路线认证仍属于 Q3（7.4/13.5），未获得这种信用；冻结设计中编写时的“样本待补”是历史状态，不将其当作已经取得线上采样证据。
