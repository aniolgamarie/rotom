# Implementation Plan: Herdr 项目工作区与可验证升级

**Branch**: `feat/herdr-native-workspaces` | **Date**: 2026-10-18 | **Spec**: [spec.md](spec.md)

**Input**: `specs/005-herdr-project-workspaces/spec.md`。feature ID 为 `005-herdr-project-workspaces`，辅助脚本的 feature ID 不改变实际 Git 分支。

## Summary

增加可选 Herdr 配置组件与薄的 `work enter PATH` / `work open ROLE [--new]`。项目归属由所选 server 的原生 worktree provenance 和 checkout realpath 确认；用途使用运行期 native metadata，不增加终端数据库。原生布局、导航和人工 shell 保持主体地位；Avalon/Agent 沿用既有入口；状态增强默认关闭。

新 tab 的公开 API 无 argv 字段，因此增加有限职责的 `rotom-work-shell`：通过 tab 环境接收非秘密的结构化启动意图，确认新 pane 与一次性关联后用 exec 参数数组启动。无意图时直接进入普通 shell。它不是守护进程，不向已有 shell 发送启动文本。

依据见 [research.md](research.md)；数据与失败状态见 [data-model.md](data-model.md)，外部接口见 [work-cli](contracts/work-cli.md)、[configuration](contracts/configuration.md)、[benchmark](contracts/benchmark.md)，分层验证见 [quickstart.md](quickstart.md)。

## Technical Context

**Language/Version**: Python >=3.11，使用已准备的仓库 `.venv`；不替换系统 Python，不固定补丁版本。入口引导代码须能在系统 Python 3.8 中转交，导入业务模块后才要求 >=3.11。

**Primary Dependencies**: 现有 PyYAML/jsonschema/Jinja2/pytest 与标准库（socket、fcntl、subprocess、tomllib、hashlib）；无新增运行时包。Herdr 使用未修改的官方稳定发行，2026-10-18 候选 v0.9.5；以后安装/升级重新显式选版，按公开协议/能力和验收判断兼容。

显式原生合成基准的可选`--offline-sockets`入口使用本机已有libseccomp及内核no_new_privs，缺能力退出5，不下载安装或影响日常work/termcfg。固定helper属于fixture，不是后台服务或Agent权限代理；独立核验实际阻断能力并保存绑定原件，见benchmark契约。

**Storage**: 原生工作区/worktree/metadata；现有 termcfg v2 state/journal/逐文件备份；机器私有 TOML。Linux每UID固定互斥文件仅为无内容进程锁，不存终端清单。基准manifest/report为显式合成输出；私人实际argv与公开normalized_argv分离，不读取真实会话。

**Testing**: 默认 pytest 仅临时 HOME/XDG、网络阻断、假子进程/假 native API。针对并发、不明结果、换端点、launcher、旧 state、秘密读取哨兵及基准误判做风险验证。原生 Herdr、SSH/客户端、Avalon 和 Agent 分层验收；用户已授权续验收并指定本机为唯一环境，Linux核心、回环SSH及部分工具启动已执行，当前状态见implementation-evidence.md。

**Target Platform**: 首轮服务器为Linux、可用procfs/O_PATH的本地Unix socket；远端客户端按实际验收组合声明，当前实体组合为macOS 26.6.2/Ghostty 1.3.1 stable。端点固定能力缺失时拒绝自动变更，不退回按路径重连。macOS/Windows服务器及其他客户端保留后续计划，不宣称通过。

**Project Type**: 现有 Python CLI 增量：两个小入口、native API adapter、配置与独立基准工具；无常驻管理服务。

**普通配置加载**: 沿用严格load_local且load_credentials=False；仅adapter-schema缺少上下文时延迟展开完整公共catalog并重验。无原生选项覆盖时不加载无关公共Agent来源，其他错误不转成功；无缓存/新配置接口。入口延迟修订T064先隔离回归及原生各200样本复验，再以新source身份重跑T051。

**Performance Goals**: 3 项目×3 checkout×3 终端=27；SC-001/002 重复/并发零重复、零额外输入。升级每暖路径每 batch >=200 样本、3 batch >=600；60 秒预热+300 秒采样。绝对预算/噪声门槛在看候选结果前校准冻结，无预算不能判性能通过。

**Constraints**: 日常离线；已有用途只聚焦；上下文不明退出 4；非 Git 在 server 操作前退出 2；无 eval/PTY 启动注入/隐式安装；不扩 Agent socket 权限；不终止现有任务、不自动恢复 Agent、不默认 live handoff。

**Scale/Scope**: 单用户、每机器一个显式 native session；7 个稳定角色；同 server 共享焦点与尺寸协调；US1–US7。首轮核心上线依赖人工终端、配置、启动和必要升级证据，US7 可关闭。

## Constitution Check

设计门禁分别于 Phase 0 前按需求、Phase 1 后按设计复核；不等于实现或平台验收通过。

| 原则 | Phase 0 前 | Phase 1 后及依据 |
| --- | --- | --- |
| I 公共核心/真实适配 | 满足 | 复用 termcfg/agentcfg；Codex 不新增适配器；未知配置失败；native 只用公开 schema |
| II 秘密/所有权 | 满足 | 普通配置 load_credentials=False；shell/edit 不解析 SecretStore；handoff 无 secrets；普通终端环境沿用原生继承，受管Agent执行前由agentcfg重新过滤/按部署引用注入；只拥有声明 TOML |
| III 确定性/恢复 | 满足 | 静态字节、逐文件 transaction/pending/备份；用途 pending 在 native metadata；不声称跨 API 原子性 |
| IV 显式副作用/依赖 | 满足 | work 不安装/部署/下载；精确官方资产收据与依赖锁独立；无包管理器扩张 |
| V 隔离/证据 | 满足 | 默认 fake API；原生/账号独立授权；四种任务状态；未执行不记通过 |
| VI 不改宿主 | 满足 | 公开 CLI/API/default_shell/扩展；无补丁或私有接缝；wrapper 为仓库自有入口 |
| VII 隐私/身份 | 满足 | 虚构路径、脱敏报告；不读账号/会话验证；本轮不提交 |
| VIII 工作树/合并 | 满足 | 保留主工作树改动；稳定 diff 审阅；提交/合并另过门禁 |
| IX 兼容/升级 | 满足 | 范围与精确资产分离；显式最新 stable；首基线不伪造 A/B；程序/配置/状态回退分开 |

无原则豁免。宪章原始批准日期是既有治理资料，不能猜填；本特性没有新增未决产品澄清。

## Project Structure

### Documentation (this feature)

```text
specs/005-herdr-project-workspaces/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/{work-cli,configuration,benchmark}.md
├── checklists/requirements.md
└── tasks.md  # plan 完成后由 tasks 工作流生成
```

### Source Code (repository root)

以下为实施文件范围；完成状态与原生缺证以 implementation-evidence.md 为准。

```text
work                              # 仓库 .venv 引导、用户 CLI
rotom-work-shell                  # 仓库 .venv 引导、native default_shell
src/termcfg/
├── work.py                       # enter/open、锁和用途状态机
├── work_config.py                # 普通配置/启动选择，不取凭据
├── work_shell.py                 # 新 pane 握手、环境消费、exec
├── herdr.py                      # 公开 API、能力、端点固定、超时
├── doctor.py                      # Herdr离线检查，新建有限辅助模块
└── {cli,config,catalog,environment,guidance,preview,transaction,state}.py  # 既有组件接缝
schemas/local.schema.json
schemas/termcfg/{machine,catalog,state}.schema.json
terminals/herdr/config.toml
terminals/catalog.json
examples/                         # 现有虚构机器示例增补
tools/bench/herdr_upgrade.py
tools/bench/client_geometry.py   # 固定nonce、owned UI及真实PTY/公开布局证明
tools/bench/cpuacct.py            # 本轮委派组的固定fd统计；不创建管理员资源
tools/bench/cpuacct_admin.py      # 管理员显式准备/仅空组清理，无常驻进程
tests/fixtures/herdr-bench/v1/
schemas/herdr-benchmark-{report,manifest,policy}.schema.json
tests/test_work_*.py               # identity/context/roles/launch/recovery/config/metadata等
tests/test_herdr_api.py
tests/test_termcfg_herdr.py
tests/test_herdr_benchmark.py
tests/test_herdr_upgrade_policy.py
tests/test_herdr_cpuacct.py
tests/test_herdr_client_proof.py
tests/test_herdr_geometry.py
tests/test_herdr_client_benchmark.py
tests/test_herdr_cpuacct_admin.py
tests/fixtures/herdr-native/v1/    # 官方公开schema/响应/静态配置与来源许可
tests/fixtures/herdr-client/v1/    # 显式实体客户端验收，只保存固定样本结果
tests/test_herdr_client_fixture.py
src/agentcfg/pi_runtime_packages.py # 原生发现的完整inventory遍历性能修复
tests/test_pi_inventory.py
locks/pi/{manifest.json,*/package-lock.json} # 通过官方入口重新生成
docs/{termcfg,local-config,herdr-workspaces,herdr-upgrades}.md
docs/templates/herdr-upgrade-report.md
```

**Structure Decision**: 保留现有 package/部署系统。`herdr.py` 是有限的原生协议客户端；`work.py` 承担项目/用途语义；业务启动委托已有入口。bench 独立，不扩大 agentcfg CLI。

原生Pi准备发现完整inventory在约5.5万个条目上反复打开祖先，导致30秒门禁超时；T061仅优化既有fd遍历并保留逐文件散列和身份检查，不增加缓存或跳过完整校验。源变化必须经官方lock重新生成四套slice，正式准备后再验收；直接来源保持不变，传递依赖差异单独记录。这不把Python/Node补丁版本改成跨机器精确门槛。

## Delivery and verification order

1. 固定 native fixture、schema、失败不变量，实现端点固定/有限请求/假 API 测试。
2. 完成Git、enter、用途状态与安全新建；未决pending阻新建（包括--new），不假设metadata重读可取消旧launcher；launcher与配置准备前不启用自动工具启动。
3. 逐文件部署、旧 state/recovery 回归；人工终端成立后衔接 editor/pi/dsh/codex。
4. 完成合成基准、report、policy 误判测试与原生验收包；授权后分层执行。
5. 可选状态扩展单独核对；无法安全接入保留关闭。稳定 diff 审阅后交付。

work管理操作默认总预算30秒；受管pi/dsh open为60秒，以容纳父调用和launcher两次完整运行包校验。等锁最多10秒、connect2秒、单请求最多5秒不变，均裁至剩余总预算。payload继承父调用同一个单调绝对deadline，launcher不重置或累加预算。原生首次27.9秒通过、第二次30秒失败的证据推翻了原统一30秒假设；完整散列和身份检查继续保留。launcher若已可能accepted但exec失败，允许额外最多2秒仅写failed/清commit，失败上报不延长业务准入；上报仍不明就退出launcher，不能进入业务程序。交互attach与已exec工具不受该预算终止。超时保留对象，不发送输入、清理或盲目重试。

## Complexity Tracking

无宪章偏离。两个入口用于安全的新终端启动；Linux 端点固定防止 server 重启后数字 ID 重用造成错误控制。不增加控制代理、daemon、终端库存或配置渲染框架。

## Native CPU measurement boundary

可选 `--cpuacct-delegation FILE`只消费管理员显式准备的本轮四空组收据；admin helper不设置配额、重挂载或迁移已有PID。runner及自己启动的子进程按driver/server/client/producer分组，单线程spawn后恢复driver，producer在READY前仅迁移自身。CPU统计使用完整内核user+system累计值；301个快照与同一300秒窗口、固定50ms端点/中点跨度容差、前后成员/PID-starttime及模块摘要绑定。平均核数以实际快照中点wall-second作分母。缺证保留原始数字和unverified，不能通过布尔标志晋升覆盖。PTY排空用owned fd非阻塞select，不引入drain线程/新daemon。默认测试不sudo或启动宿主，真实短命/线程/双fork挑战与Herdr窗口分别记录。

### T065专用基准server收尾修订

projects-27单batch的400个warm样本达原预算、重复/并发正确性通过，但跨workspace逐pane close遇原生退出1，整份报告仍failure。case结束前fresh查询全部pane，要求与登记owned的pane_id/terminal_id/workspace_id三元组集合完全一致、无缺失/重复/替换后，一次官方server stop关闭专用server；未知对象保留并拒绝。保持confirm_close与窗口/预算不变；T065隔离回归及新完整projects单batch正常收尾后方可完成T064，T051使用新runner/measurement/source封印的新epoch。

### T066本轮校准的明确例外复核

用户已在知晓偏差规模、预热与正式CPU窗口无重叠及正式计数完整后同意继续。该接受仅针对原报告的唯一1行预热计数偏差，不是事前规则或新通用容差。保留测量引擎、三schema、fixture及manifest/source全部冻结，以仓库外一次性审阅器严格核对同一原报告/批准/原件，保存独立接受及provenance；原report仍invalid。由原pending policy派生的预算/回归/noise参数不得变更；首基线仍完整三批、正式计数与全部门禁严格。compare通过原公开Python的校准复核参数衔接，只有显式例外与原件复核成功后才设为true，不monkeypatch、不修改任何report。该人工审阅路径区别于仍会拒绝该invalid校准引用的原CLI；返回原schema合法comparison供未来baseline acceptance引用，另存审阅来源摘要。实现不引入产品级豁免框架。

### Target-main reference refresh during immutable candidate measurement

共享main前进触发首次首基线在测量前退出2，原失败保留。候选未合并/rebase，因此Root明确细化引用契约：新manifest仅允许ID后缀、source.target_main及digest改变；原校准按原manifest、严格候选按新manifest核验，另存完整相等性证明和provenance，不利用verify_calibrations的绑定缺口。测量引擎、schema、policy、source/lock/asset/subject/负载/采样/隔离路径完全不变；任一实际受测输入变化须重新校准。此证据不证明与新main合并后的Agent集成，不能授权合并或生产切换。
