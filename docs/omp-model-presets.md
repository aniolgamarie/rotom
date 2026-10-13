# OMP 模型套件

模型池提供可选型号，套件配置日常执行、轻量任务、深入分析等角色的组合。rotom 将 `agent_options.model_presets` 转换为 OMP 官方 `modelPresets`；使用固定 v18.8.6 的公开配置与命令，不修改上游源码。

`omp-default` 提供 `basic` 和 `deepseek-payg`，其初始角色使用 basic。`omp-kernel` 在其基础上提供 `tf`、`cursor`、`deepseek-tf-payg`，共五套；kernel 的全局初始角色仍使用既有 TF 配置，私人 Cursor 角色覆盖仍优先。新增预设不会自动切换已有部署或登录账号。

## 角色组合

| 角色 | basic：官方 Coding Plan | tf：企业网关 | deepseek-payg / deepseek-tf-payg |
| --- | --- | --- | --- |
| main / 原生 default | Kimi Code · high | Kimi TF `kimi-for-coding` · high | 对应入口 `deepseek-flash` · high |
| smol | GLM `glm-5.3-flash` · low | GLM TF Flash · low | Flash · low |
| slow | Kimi Code · max | Kimi TF `k3` · high | Flash · max |
| plan | GLM `glm-5.3` · high | GLM TF `glm-5.3` · high | Flash · high |
| task | Kimi Code · high | Kimi TF `kimi-for-coding` · high | Flash · high |
| advisor | GLM `glm-5.3` · high | GLM TF `glm-5.3` · high | Flash · max |
| vision | GLM Flash · high | GLM TF Flash · high | Flash · high |
| tiny | 本地 `lfm2.5-230m` | 相同 | 相同 |

Kimi Code 对应 `kimi-for-coding`；basic 和官方 DeepSeek 使用仓库默认的 Anthropic 兼容入口。DeepSeek Pro、K3 的其他版本和 HighSpeed 保留在模型池中，此轮没有把它们加入基础角色组合或自动付费备用链。

Cursor 使用下列逻辑 ID：

| 角色 | 原生 selector |
| --- | --- |
| main | `cursor/kimi-k3:high` |
| smol | `cursor/composer-2.5:low` |
| slow | `cursor/kimi-k3:max` |
| plan | `cursor/glm-5.2:high` |
| task | `cursor/composer-2.5:medium` |
| advisor | `cursor/grok-4.7:high` |
| vision | `cursor/kimi-k3:high` |
| tiny | `local/lfm2.5-230m` |

这些候选来自 2026-10-06 本机 OMP 最近一次账号范围模型目录缓存；不是官网全量型号，也不是实时推理成功证明。Kimi K3 的档位为 low/high/max，Cursor GLM 5.2 为 high/max，Composer 2.5 为 minimal/low/medium/high，Grok 4.7 为 low/medium/high/xhigh。未加入该账号目录中缺席的 GPT、Claude 或 Gemini 型号。Cursor 的 GLM 5.2 与官方 Coding Plan GLM 5.3 是不同接入项，不按名称互相升级。

Composer 缓存上下文为 200000，Grok 4.7 为 256000，GLM 5.2 为 1000000，Kimi K3 为 1048576。长会话换到较小模型时需要先处理上下文预算。图像能力还须符合实际传输；TF 图像请求、账号当前权限和额度需另行真实验证。默认 Cursor 组合只使用上述已核对候选；私人自定义 Cursor selector 只验证所选 OAuth provider、语法和已知档位，不将静态声明当作实时账号许可证明。

## 切换与配置所有权

部署这轮配置后，在 OMP 会话中使用官方命令：

```text
/modelpreset list
/modelpreset switch basic
/modelpreset switch tf
/modelpreset switch cursor
/modelpreset switch deepseek-payg
/modelpreset switch deepseek-tf-payg
```

`./agentcfg model presets` 是 rotom 的官方模型池列表命令；`/modelpreset` 是 OMP 的角色套件命令，两者用途不同。

角色存储使用 `modelRoleStorage: project`。原生切换写当前工作目录的 `.omp/config.yml`，全局受管初始角色保持原样。预设为八个受支持角色完整指定模型，每个远程模型携带思考档位，未设置 `defaultThinkingLevel`，因此切换不改全局思考等级。下次在同一目录启动会读取项目角色；切到子目录不会按祖先继承该文件；祖先的角色文件也会经过相同校验，合法的仅角色文件不会阻止子目录启动。

项目文件只允许 `modelRoles`，包含 default/smol/slow/vision/plan/advisor/task/tiny 的部分或全部赋值；空文件或空映射可恢复全局角色。每个角色只接受已声明套件或明确全局初始角色中的同一模型与档位，tiny 只接受固定本地型号。模型仅在可选池中存在，不等于允许项目文件把它改成执行角色；例如未分配的 DeepSeek Pro 和未声明的 Cursor 型号会被拒绝。需要长期自定义角色时先写私人角色覆盖或 `agent_options.model_presets`；单次模型选择可使用 OMP 会话的 `/switch`。运行前拒绝其他设置、重复键、YAML 别名、链接、非常规文件及超限文件。启用项目角色不等于启用项目 skills、MCP、插件、权限配置或认证配置。

rotom 按预设名称管理 `/modelPresets/<name>`，保留用户通过 `/modelpreset save personal` 新建的其他名称。用户自建预设若引入声明组合之外的角色，也应先写私人意图，才允许项目角色持久化。修改同名受管预设会报告漂移，应修改私人 `agent_options.model_presets` 意图后 plan/apply；不要用原生 save 覆盖受管名称。私人角色覆盖仍决定全局初始配置，用户主动选择项目预设后，项目角色按照 OMP 的公开优先级生效。

## 备用链和权限审批

OMP 原生预设只切角色，不切 `retry.fallbackChains`。本轮将执行备用链改成按具体入口、模型及档位匹配：basic 在官方 Kimi/GLM 间备用，tf 在 Kimi TF/GLM TF 间备用，cursor 仅保留 Composer 2.5 到 Kimi 2.7 Code 的两条备用链。K3 使用实际目录成员的无档位空链 `cursor/kimi-k3-low/high/max = []`（三个独立键），GLM 5.2 high/max 和 Grok 4.7 high 的空链保持。preset 的 `cursor/kimi-k3:档位` 是逻辑 picker 名；官方 resolver 结合当前实际成员 metadata 选中成员空链，防止落到角色或默认链。逻辑名不是注册的 model ID，因此不再把它写为备用链键，避免启动 unknown model 告警；不使用 Cursor provider 通用空链。Cursor K3 的历史校验拒绝其他模型生成的 assistant 历史，连 error/aborted assistant 也会触发；恢复 K3 应在新会话进行。这项配置修正阻止默认自动切换继续混入异型号历史，已受影响的历史不自动修复。详见[历史兼容边界](follow-ups/omp-cursor-history-2026-10-09.md)。移除了 kernel 原有的角色通用 TF 链和旧 GLM 默认依赖。相同模型与档位在不同角色中共享执行备用链；没有把 DeepSeek 按量模型放入订阅/TF/Cursor 的自动链。

两套 DeepSeek 由用户主动切换启用，不自动跨官方/TF 入口，也不自动接 Pro。未配置的模型故障由原生重试和错误处理负责，不能把“可选池中存在”当作自动备用授权。

权限审批与执行套件独立。kernel 公开默认 `reviewer_model` 固定为 GLM TF Flash，`remote_fallback_model` 为 Kimi TF `kimi-for-coding`；有效 allow/ask/deny 不复审，运行故障才尝试远程备用。tiny 仍为 installed-only 的保守 ask/deny 兜底。私人显式主审、备用及模式设置优先，套件切换不会修改权限 sidecar。用户可在私人覆盖中显式设置 `reviewer_model = "session"` 恢复跟随会话；省略私人字段会保留公开默认。`remote_fallback_model` 仍要求选中的具体模型，不能设置为 session。跟随会话时仍适用原有传输不支持后的备用规则。

离线配置验收见[实现记录](acceptance/omp-model-presets-20261006.json)。2026-10-07 已完成 workstation 的 omp-kernel 本机部署，五套预设、备份、受管配置与无宿主启动准入均已核验，见[本机部署记录](acceptance/omp-model-presets-local-deploy-20261007.json)。真实会话切换、当前 Cursor/TF 推理与图像传输仍未验证；basic 的官方订阅 key 与 DeepSeek TF 独立 key 尚需填写。
