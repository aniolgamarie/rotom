# 模型目录与 provider 绑定

核验日期：2026-10-06。模型池提供可选型号；角色配置决定实际使用的组合。此轮更新目录，没有新增 OMP 模型套装，也没有改变现有执行模型、权限主审或备用角色。

`shared/model-templates.toml` 集中维护型号、输入类型、上下文、输出预算和推理能力。`shared/models.toml` 与 `agents/omp/content.toml` 引用模板，分别维护 provider、协议兼容和费用。相同型号在官方 OpenAI、官方 Anthropic 和 TF 绑定间共用核心规格，网关可用性、套餐资格和计费不会因此自动继承。

## 官方可选池

每种工具默认加入八个官方型号，使用三个 API-key provider。DSH/Pi 默认选 OpenAI 兼容路线，OMP 默认选 Anthropic 兼容路线；另一协议的定义保留，可显式启用。未指定主模型时仍使用 Kimi Code `kimi-for-coding`，已有显式角色优先。

| 服务 | Provider | 远端模型 ID | 上下文 / 客户端输出预算 | 配置输入 |
| --- | --- | --- | --- | --- |
| Kimi Code 订阅 | `kimi_code_openai` / `kimi_code_anthropic` | `kimi-for-coding`（K2.8 Preview） | 1048576 / 32768 | 文本、图像 |
| Kimi Code 订阅 | 同上 | `k3` | 1048576 / 131072 | 文本、图像 |
| Kimi Code 订阅 | 同上 | `k3-256k` | 262144 / 131072 | 文本、图像 |
| Kimi Code 订阅 | 同上 | `kimi-for-coding-highspeed` | 262144 / 32768 | 文本、图像 |
| GLM Coding Plan 订阅 | `glm_coding_openai` / `glm_coding_anthropic` | `glm-5.3` | 1000000 / 131072 | 文本 |
| GLM Coding Plan 订阅 | 同上 | `glm-5.3-flash` | 1000000 / 131072 | 文本、图像 |
| DeepSeek 官方按量 API | `deepseek_openai` / `deepseek_anthropic` | `deepseek-flash`（V4.1 Flash） | 1048576 / 393216 | 文本、图像 |
| DeepSeek 官方按量 API | 同上 | `deepseek-v4-pro`（V4 Pro 0813） | 1048576 / 393216 | 文本 |

Kimi Code 的四个 ID、会员门槛和能力以[官方型号页](https://www.kimi.com/code/docs/en/kimi-code/models.html)为依据。`k3` 的 1M 上下文要求更高会员等级；权限不足时应选 `k3-256k` 或按账号额度覆盖上下文。K3、K2.8 Preview 支持 low/high/max，HighSpeed 只声明 Thinking ON，不虚构多档推理等级。Kimi 输出数值采用仓库固定的官方 OMP v18.4.5 SDK 客户端预算，并非已核实的服务端最大输出量。部分 Kimi 型号支持视频，但当前工具模型配置只声明文本和图像。

GLM-5.3 与 Flash 均在 [Coding Plan](https://docs.z.ai/devpack/overview) 范围内；[Flash 官方文档](https://docs.z.ai/guides/vlm/glm-5.3-flash)确认原生图像能力。两者思考不能关闭，支持 low/high/max；Pi 配置禁用 off，OMP 使用公开 `thinking.requiresEffort` 能力字段。上下文采用保守的 1000000 token 客户端预算。FlashX 属于另一路线，没有加入 Coding Plan 池。国际 Z.AI 与中国 BigModel 的接入约束不能混用；这里保留[中国 Coding Plan 官方接入](https://docs.bigmodel.cn/cn/coding-plan/tool/others)的 OpenAI 和 Anthropic 地址。视频、文件等服务能力未加入当前 agent 输入枚举。

DeepSeek 两个 ID 的规格依据[官方模型目录](https://api-docs.deepseek.com/api/list-models/)。Pro 仍按独立型号登记，以[更新日志](https://api-docs.deepseek.com/updates/)后续说明为准，不沿用已被后续公告覆盖的 Pro 路由至 Flash 的旧判断。low/high/max 档位、工具历史消息和 tool choice 限制按[思考模式文档](https://api-docs.deepseek.com/guides/thinking_mode/)分别适配。官方费用按[价格页](https://api-docs.deepseek.com/quick_start/pricing/)保存 2026-10-06 快照，不复制给 TF，也不冒充原生工具支持币种和分时费率。

DSH 当前只投影容量字段，不提供完整推理模式约束。目录中的能力记录不等同于每个宿主均能强制执行全部模式限制；没有通过补丁改变宿主行为。

## TF 追加目录

TF 仅由选择它们的 profile 引入，`omp-kernel` 默认追加以下十一条绑定，与官方池合计十九条静态绑定。现有 TF 角色和已有费用字段保留。

| Provider | 协议 / 地址引用 | 凭据引用 | 模型 ID |
| --- | --- | --- | --- |
| `kimi_tf` | OpenAI / `local:tf_openai_url` | `secret:omp_kimi_tf_key` | `kimi-for-coding`、`k3`、`k3-256k`、`kimi-for-coding-highspeed` |
| `zhipu_tf` | Anthropic / `local:tf_anthropic_url` | `secret:omp_zhipu_tf_key` | `glm-5.3`、`glm-5.3-flash`、`glm-5.2`、`glm-5.1`、`glm-5-turbo` |
| `deepseek_tf` | OpenAI / `local:tf_openai_url` | `secret:omp_deepseek_tf_key` | `deepseek-flash`、`deepseek-v4-pro` |

GLM 的旧三个 TF ID 保留为独立候选。官方 Coding Plan 对旧型号的升级/别名规则不作为 TF 网关同样路由的证据；旧型号未核实的多档推理映射不新增。DeepSeek TF 使用独立 key，可通过 `model key deepseek_tf` 填写；复用地址不意味着复用密钥。TF 的实际 ID 支持、能力、路由和计费尚未进行真实请求验证。

全目录共有十一份核心模板、二十七条静态模型绑定（官方十六条、TF 十一条）。provider 共十一项：六个官方协议入口、三个 TF 入口、两个已有动态 OAuth 入口（Cursor、Codex）。动态发现的 OAuth 模型不计入静态绑定数量。

`./agentcfg model presets --verbose` 查看公共官方池，`model status --verbose` 查看当前 profile 的实际选择、地址/凭据缺项与角色。公共模板展开后仍使用原有 adapter 接口，私人文件的模型覆盖格式不变；不支持在私人机器文件里声明模板。
