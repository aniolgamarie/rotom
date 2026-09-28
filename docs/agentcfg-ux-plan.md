# agentcfg 命令交互简化方案

## 现状与目标

首次部署要求用户手写 `default_profile`，重复输入机器选择器，依次运行 `validate`、`plan`、`sync`、`apply`、`doctor`，并从单行 JSON 找结果。日常 `run` 又要求重复输入已经由 profile 决定的 agent。

目标是提供一条较短的首次部署路径，同时保留原有细粒度命令、JSON 输出、退出码和脚本兼容性。

## 本轮实施

1. `profiles` 只读列出仓库登记的 profile ID 和所属 agent，不读取本地配置或凭据。
2. `init-local [--machine NAME] [--profile ID]` 可指定机器和默认 profile；省略时使用 `default` 机器与 `dsh-default` 配方。显式非默认 ID 在创建目录前与仓库登记项核对；默认配方检查固定登记文件存在，保留原有不读取目录内容的初始化契约；不覆盖已有文件。
3. `setup` 依次做离线校验、脱敏预览、依赖同步和部署。预览有冲突、漂移或待恢复事务时，在同步之前返回 4。输出简短中文摘要，明确同步可能联网、部署会写入实例。同步失败立即停止。同步后重新读取配置与锁，沿用 `apply` 的生命周期锁、恢复和冲突检查；在写锁内再次比对完整预览，变化时停止，不复用旧候选。
4. `run` 可以省略 agent，由选中 profile 推断；显式 agent 仍须匹配。原生参数仍放在 `--` 后并保持原样。
5. 更新入门与 OMP 文档，使用短路径，并保留分步命令供审阅与排障。
6. `setup` 与 `sync` 的固定阶段进度写入 stderr；耗时同步定时报告已等待时间。失败报告阶段、退出码与下一条诊断命令，保留各后端原有脱敏错误，不输出安装器原始日志。

示例：

```sh
./agentcfg profiles
./agentcfg init-local --machine workstation --profile omp-kernel
./agentcfg --machine workstation setup
./agentcfg --machine workstation run --cwd /absolute/project
```

## 兼容与安全边界

- 原命令和 JSON 输出保持不变；`setup` 是显式执行安装与部署的新命令，不自动启动宿主或读取原生账号。
- `setup` 的人类摘要只含 profile、agent、变化/漂移/冲突数量和依赖状态，不显示配置值、动态路径或凭据引用。
- `init-local` 仍创建权限为 0600 的私人文件，文件已存在时返回 4；未知 profile 返回 2 且不写入。
- `usage` 的原生透传及其受管/非受管选择语义不变。

## 私有模型配置

`model add` 已实现单个静态 API-key 模型的交互输入：provider、model、角色、能力和必填密钥一次收集，先走完整 schema/适配器与候选产物校验，确认后 CAS 原子替换私人文件。局部编辑器仅处理可明确定位的表和单行字段；写前用完整 TOML 语义比较确认提案只改变目标字段。复杂多行格式会拒绝自动编辑，保留原文件供手动处理。OAuth、已有实体更新及批量模型目录仍是后续范围。

`doctor` 对 DSH、Pi、OMP 共用离线就绪判断，给出部署、依赖、恢复和漂移的固定状态码及下一条命令。`doctor --input` 对三者共用诊断命令终端的标志；只有 OMP 提供受管事件循环阻塞日志，DSH/Pi 明确返回无受管事件源。阶段进度与失败阶段覆盖校验、预览、部署、启动及模型向导；输入状态栏属于 OMP 原生界面能力。

## 方案 review

独立 review 指出：预览与同步之间状态可能变化，部署必须重新计算候选；冲突、漂移、待恢复应在同步前停下；`run` 省略 agent 时要调整匹配判断；并覆盖未知 profile 零写入、同步失败不部署及摘要脱敏。这些要求已纳入上述实施与回归验证。
