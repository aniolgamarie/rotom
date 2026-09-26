# OMP kernel 跨机器可用性修复

日期：2026-09-26。用户授权修复下载中断、在 rotom 仓库内启动失败、kernel 配置未复刻。目标机器为 WSL，发行版/架构及原始报错尚未提供。旧 spec 002 的历史验收保留，本记录跟踪新增修复范围。

## 已完成

- 只读核对本机 kernel 的两组 provider、9 个模型、模型角色/回退、76 条 Bash 规则、5 条拦截规则、主题、5 个原生 agent 和技能来源。
- 复现仓库来源门禁在关闭和开启 project_resources 两种策略下均拒绝 rotom 仓库。
- 下载流式缓存、有限重试、断点续传、错误诊断和坏缓存恢复。
- 根据固定上游真实加载路径修订项目来源检查。
- omp-kernel 正式配方、严格原生设置映射、完整资源及秘密引用迁入。
- 完整资源锁更新、WSL 使用说明及迁入差异清单。
- codex-delegate 默认直连、显式机器代理、包内相对路径和五组假 Codex 自测。

## 进行中

- 无；本轮实现、锁更新和隔离验收已完成。

## 失败待决策

- 无；发现不能等价迁入的原生设置时记录具体差异，不静默丢弃。

## 环境不足未验证

- 用户 WSL 实机尚无远程执行环境；保留待用户验证。
- macOS 与 Linux arm64 仍按 OMP-F01–F02 单独跟踪，不将当前隔离测试计为实机通过。
- 真实登录、usage、模型调用继续按 OMP-F03–F05 单独跟踪。

## 迁入处置与兼容说明

| 来源 | 当前处置 |
|---|---|
| kernel `models.yml` | 两个 provider、九个模型、协议、兼容参数、显示名、容量、输入类型、reasoning、cost 纳入公共声明；API key 替换为私人 SecretStore 引用 |
| kernel `config.yml` | 主题、五个在线模型角色及 thinking、tiny 选择、cycleOrder、fallback、审批/Bash、task、LSP、statusLine/display/composer/tui、关闭的 memory、compaction、setupVersion 逐项映射；隔离部署对照测试覆盖 |
| 原生 skills 发现开关 | 四个 Pi-user 技能显式复制为受管完整包；不再依赖旧 HOME。项目/外部工具发现由管理器策略替代，默认不加载项目 `.pi/.codex/.claude` 内容；这项是有意的来源策略差异 |
| 五个原生 agents | 同名完整 Markdown 纳入资源锁和部署；frontmatter 只允许已支持的声明字段，文件漂移在 spawn 前拒绝 |
| 确认规则 | 作为受管 RULES.md 内容部署，保留正文 |
| Kanagawa 主题 | 保留全部受支持颜色；移除与 mdLink 相同的额外 link 字段，固定 v18.3.0 schema 不接受该额外字段 |
| 技能包 | 保留相对资源、脚本执行位和测试；排除历史 .bak 文件，示例中的本机路径改为可迁移位置，假凭据哨兵改为明确 SYNTHETIC 名称；codex-delegate 改为默认直连、显式无凭据代理只注入 child，测试使用包内路径 |
| 登录、数据库、会话、日志、缓存 | 保留旧环境，未读取正文或复制 |
| 本地 tiny 模型权重、Codex CLI/认证、LSP 服务程序 | 属于各机器运行依赖；资源配置可以复刻，不因此声称这些依赖已安装或实机验证 |

固定源码依据：OMP v18.3.0 / `62bc57be1b03ef0802a33cf7f5f530e534527531`。`capability/index.ts` 的 whole-provider 禁用与 foreign-user opt-in 不同；已禁用 provider 的项目目录可忽略。`task/discovery.ts` 的 `.omp/agents`、native direct helper、dotenv 与 `PI_CONFIG_FILES` 独立来源仍需检查。

## 验证记录

- 下载与依赖专项：47 passed / 1.63s；随后补 HTTP IncompleteRead、完整错误响应及无 Content-Length 的 Range 跨度校验。
- 仓库来源专项：111 passed / 1.64s；默认与显式 project opt-in 均能在真实仓库形状下启动假进程，原生危险来源负测保持零 spawn。
- kernel/adapter/resources/schema 与下载组合：139 passed / 6.63s。
- 临时机器文件按新示例执行 CLI `validate`、`render`、`plan`、`doctor` 均退出 0；未安装真实运行包、未调用 sync 或启动宿主，doctor 的未部署/缺依赖状态不计宿主通过。
- 首轮全量：1 failed, 2193 passed, 7 subtests passed / 144.85s。唯一失败是静态 schema 测试仍依赖旧 `$defs/profile` 结构，已更新为实际 schema 结构和三类资源；相关组合 42 passed / 10.87s。
- Codex 技能包五组自测（delegation、multiturn、runner、progress、observe）全部通过；仅运行 bundled fake Codex；所有 shell 文件通过 `bash -n`。
- 正式锁：`09e48f2e84cfe9d228da05161ff5360cbe6386296d266e144556d8f025de449b`，155 个资源、17 个配方输入，重新读取验证通过。
- 最终配方 CLI `validate/render/plan/doctor` 均退出 0（临时 HOME、空 key）；60 个变更文件无源密钥泄漏，86 个相对 Markdown 链接有效，无尾随空格。
- 第二轮全量：1 failed, 2197 passed, 7 subtests passed / 150.51s。发现 thinking 捕获扩展将重复原生模型映射覆盖；已恢复显式唯一性检查，capture/kernel 专项 19 passed / 7.79s。
- 最终全量：`2198 passed, 7 subtests passed` / 153.97s，无失败。

执行分工：主代理负责 kernel 配置映射、身份/来源决策、集成验收与完整锁；executor 实际模型 gpt-5.6-sol / medium 负责下载、来源回归和用户文档；scout 实际模型 gpt-5.6-luna / medium 负责固定上游证据与独立核对。所有 Python 默认测试使用临时 HOME、假进程和网络阻断；未将用户 WSL 或真实 API 调用记为通过。
