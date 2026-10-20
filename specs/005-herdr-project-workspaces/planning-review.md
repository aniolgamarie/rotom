# Planning and analysis record

2026-10-18开始，2026-10-19完成。实际分支 `feat/herdr-native-workspaces`，feature ID `005-herdr-project-workspaces`；起始HEAD与目标main为 `93e4f7899725336c1180e53b4ec239eea5f984ce`。本记录只证明规格、设计与任务准备，不是实现或原生验收成绩。

## Delivered artifacts

- [plan.md](plan.md)：技术栈、范围、前后宪章门禁、源文件布局与交付顺序。
- [research.md](research.md)：tagged接口证据、方案选择与已知限制。
- [data-model.md](data-model.md)：项目、用途、pending、失败与恢复状态。
- [work-cli contract](contracts/work-cli.md)、[configuration contract](contracts/configuration.md)、[benchmark contract](contracts/benchmark.md)：外部接口和安全失败行为。
- [quickstart.md](quickstart.md)：分层验证指南，标明拟新增命令尚未实现。
- [tasks.md](tasks.md)：60条未执行任务、7故事、44项需求覆盖、依赖与并行示例。

## Analyze / revise loop

每轮分析只读。修订在该轮分析结束后独立进行，再运行prerequisite检查和下一轮分析；用户已明确授权循环修订。未修改宪章以消除冲突，未改变用户已确认的open上下文约束。

| Round | Findings | Severity | Subsequent remediation |
| --- | --- | --- | --- |
| 1 | C1、I1、I2、I3、I4、U1，共6项 | 1 critical、4 high、1 medium | 私人实际argv/公开normalized_argv分离；不覆盖pending；固定UID锁；合成editor替身；正确性failure优先；canonical摘要规则 |
| 2 | U2、U3、I5，共3项 | 1 high、2 medium | 明确failed/accepted登记与未知pending延迟恢复runbook；固定fixture配置锚点/实例映射；所有新建要求workspace无pending |
| 3 | I6，共1项 | 1 medium | 每次复用核对phase/commit；已登记后exec失败转unknown/4并保留pane；初始shell使用完整交接标记 |
| 4 | 0项 | 0 critical/high/medium/low | 前10项均闭合；独立只读复核未发现新增可操作问题 |

最终覆盖：34 FR+10 SC=44，44/44有任务（100%）；60任务均有需求或治理依据，无未映射任务，歧义0、重复0。故事任务数US1–US7分别6/8/4/7/7/10/4；共享Setup3、Foundation7、Polish4；20个[P]标记有不同文件与前置说明。完整映射见tasks.md末尾覆盖表。零文档发现不证明实现并发正确或平台通过。

## Verification evidence

公开记录的命令均为normalized_argv/逻辑路径，私人原件与公开规范化记录不能混称。

| Check | Normalized invocation / method | Exit / result |
| --- | --- | --- |
| plan setup | .specify/scripts/bash/setup-plan.sh --json | 0；已生成模板并解析feature路径 |
| tasks setup | .specify/scripts/bash/setup-tasks.sh --json | 0；读取模板、spec/plan和四组设计材料 |
| analysis prerequisites | .specify/scripts/bash/check-prerequisites.sh --json --require-spec --require-tasks --include-tasks | 四轮均0；必需文件齐全 |
| 文档结构/链接/格式/隐私 | .venv/bin/python -I，标准库临时checker | 0；核心10个Markdown、36个相对链接、2段TOML、4个JSON argv示例有效；任务T001–T060连续、60条全未勾选、20条P、44项精确覆盖；无尾空格/私有用户名路径/未决产品标记 |
| whitespace | git diff --check，另扫描全部未跟踪feature文档 | 0；无空白错误；不能只用git diff检查未跟踪文件 |
| Linux endpoint机制 | 临时目录、自有Python AF_UNIX listener与O_PATH/procfd实验 | 受限沙箱bind不允许，随后受控本地执行0；替换路径仍连旧listener，旧listener关闭后errno111，不连新listener。只证明本机内核机制，未启动Herdr |
| stable再核对 | 官方releases/latest，2026-10-19 | 仍指向[v0.9.5](https://github.com/herdrdev/herdr/releases/tag/v0.9.5)；只作为当前候选，不是永久版本门禁或资产安装证明 |
| hooks | .specify/extensions.yml存在性 | 不存在，无before/after plan/tasks/analyze hook待执行 |

`requirements.md`已勾选的“无待澄清标记”检查项包含标记字面说明，不是未决项；原宪章批准日期保留既有待维护者确认资料，不猜填。本轮未改这两处治理/规范事实。

未改基线的摘要复核：

| Artifact | SHA256 |
| --- | --- |
| spec.md | 642735fcf2adac345c38a83d4008cba8dbeeb5672f0c4c38051f8097d525c8df |
| checklists/requirements.md | e2cf55bfdf672d40e710cde59033be590e1740bdcd59043afcc31a299ab0f78c |
| constitution.md | fe29290cac803d92a3f6576b36584eb8388f819edc05fb0b7c6a0b1b3d72e3d2 |
| 历史OpenSpec材料aggregate | 65f2b0a4ecee2425af1399385d5e5ede3170595dd3168aa82d0da2a823c95c78 |

aggregate按相对文件名排序，以UTF-8文件名+NUL+原始bytes+NUL计算；本轮没有改写历史OpenSpec材料。宪章顶部临时Sync Impact Report按既有规则留待未来提交前移除，本轮不提交。

## Delegation and remaining status

委派使用角色固定配置：executor为gpt-6.1-sol/medium，负责两个Phase1文档和tasks生成；scout为gpt-6-luna/high，负责原生接口/仓库证据与独立分析。主代理负责端点、锁、启动/恢复语义取舍和最终稳定工件验收；无子代理继续派生。模型名称来自角色配置，不是额外的后端遥测证明。

| Work | Status | Evidence / remaining work |
| --- | --- | --- |
| plan、research、模型、contracts、quickstart、tasks | 已完成 | 文档检查、四轮分析、10项修订闭合 |
| 分析发现待修订项 | 已完成 | 最终0项，无实际失败待决策遗留 |
| 代码和默认fake-host测试 | 环境不足未验证 | 本轮仅准备工件，未实现或执行pytest；所有60任务保持unchecked |
| 原生Linux Herdr/有效配置/SSH客户端 | 环境不足未验证 | 需实现和对应显式授权；未连接真实server |
| Avalon/真实Agent/账号/模型调用/状态扩展 | 环境不足未验证 | 逐工具与实例独立验收；状态默认关闭 |
| 性能校准/首基线/升级A/B/canary/回退 | 环境不足未验证 | 无生产性能基线；需冻结预算、授权和真实数据，不能从文档推定通过 |

主工作树无关改动保留；没有安装、提交、合并、远端写入、生产入口切换或存量进程迁移。下一阶段可按tasks.md实施，原生/账号/推广仍遵守已列授权边界。
