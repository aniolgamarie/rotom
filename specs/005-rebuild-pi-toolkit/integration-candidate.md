# Pi 集成审阅候选（2026-10-19）

本记录覆盖从目标 `main` 重放的本地审阅候选及合入门禁。原 `design/pi-toolkit-reboot` 工作树保留，
[本轮交付验收](current-delivery-acceptance.md)中的真实运行结果继续绑定其原源码和锁。
本候选的隔离检查、原生未执行范围及提交状态单独记录。

## 来源与重放范围

目标 `main` 为 `93e4f7899725336c1180e53b4ec239eea5f984ce`，原 reboot HEAD 为
`8ac50aaa8168b8a377c59736eaa1aebeb83a48c6`，共同祖先为
`5e1a042ec05afe99a80ade84f4aded06cd7c1a9a`。两侧分别有四个和一个线性提交。
分叉本身不证明历史是否经过公开清理；本轮选择从 `main` 重放已审阅内容，避免引入额外父历史。

新工作树分支为 `review/pi-toolkit-reboot-main`，从上述目标 `main` 创建。
实现已在用户明确批准当前公开身份后本地提交为
`3d41daba91d1d08a3d5c7fb48a65fa10aff2f5db`，父提交即上述目标 `main`，
提交树为 `993386112f99e76b05bd8029045a7ffd734d8727`。未复制旧提交元数据。
任务路径清单共 2369 项，八份旧设计草稿的退出已包含在其中：
152 项复制、2198 项删除、8 项在目标中原本不存在、11 项交集交由主代理处理。
机械阶段非交集逐字节和模式核对通过，89 项仅 `main` 变更的路径与目标 Git 对象一致。
后续按现行 Pi 契约适配其中的 cli_help 和两份交互测试，其余 86 项继续保持目标内容。

11 项交集包括六份文档、CLI/config/presentation/runtime 四个公共模块及模型默认值测试。
保留 `main` 的 DSH SSH、CLI 交互、身份与计划环境检查、部署待恢复和依赖锁提示；
同时保留 Pi 新 runtime/backend/lifecycle 接线、verification/feature_readiness 投影和旧执行链退役。
presentation 的七处冲突按上述边界处理；known-issues 的一处冲突保留两侧有效内容。

宪章临时 Sync Impact Report 已按治理要求移出提交内容，审阅副本保存在私人存储。
宪章条文、版本和原始批准日期待确认项未变。没有读取真实密钥、认证或会话数据。

实现提交 `3d41daba…` 的生产输入为 318 文件，摘要为
`7e73dcee00f3d5a0b8f24825974dfa36a574137338970e817c0a8b2762202972`。
范围为 Git 可见且实际存在的 src、agents、shared、schemas、profiles 文件；按路径排序的
`[path,mode,sha256(body)]` 紧凑 JSON、`ensure_ascii=True` 再 SHA256。
相对原 305 文件新增 13 项 main 来源文件。默认 Pi 锁仍为
`522bed3a9815e84ad88235956fa0da8bd21625d59c9126af262659a0288396e7`。
该次完整回归期间测试输入保持不变，回归结束后生产摘要也与运行中记录一致。
后续合入前发现并修订的启动策略及新来源身份见下节，不把本次摘要回填前面的证据。

## 合入前启动策略修订

原生复验发现：固定官方 Pi 的交互启动会为缺失的 `fd/rg` 自动下载 Linux GitHub latest
发布物，完整 npm 闭包没有固定这些外部工具。这与启动不得隐式安装的规格边界不一致。
仅修改仓库自有 Pi 适配：新启动契约声明官方 `PI_OFFLINE=1`，环境调整阶段固定同值，
使尚未重新 apply 的旧部署也采用该策略；环境继承及 unset 不得覆盖该保留变量。
未修改宿主、node_modules、依赖版本或正式锁，也没有增加执行器。

官方标志抑制工具/扩展包的启动下载、模型目录刷新、版本及相关更新路径，
不阻断模型请求或 MCP 连接，也不是通用网络沙箱。`fd/rg` 作为机器前提由操作者显式准备，
不把 UI 启动或 npm doctor 通过当作搜索工具通过；旧原生缓存保留。
精确外部前提及影响见 [Pi 指南](../../docs/pi.md)。

修订后仍为 318 个生产文件，仅 `src/agentcfg/pi.py` 相对实现提交改变，摘要为
`4aa362a65db3ef8f114d39c1ad446af5eaa4fc3115197e4ee56dac5d137d73a3`。
旧部署缺少新声明、调用环境未设/空值/0、禁止 inherit/unset 均有隔离回归；
连同三类精确环境期望的消费者，定向 73 passed、exit0。最终 33 文件受影响回归为
895 passed、exit0；pytest 411.65 秒、执行器 412.06 秒，测试文件与 Pi 源码在运行前后保持不变。
该结果覆盖前述 890 项范围及新增五项，不能把定向、早期通过和最终回归相加。
测试控制器一次误解虚拟环境解释器路径导致零测试，另两次在新增公共环境项的旧精确断言
处早停；原记录保留，消费者期望已修订，未放宽隔离或取消边界。

## 整合修复

- 逐文件删除留下空目录，首次退役断言失败。确认 31 个明确退役根在原工作树均缺失，
  新树下没有任何文件或符号链接后，用 rmdir 清理 220 个空目录，删除正文 0；失败单验通过。
- main 新帮助及两份测试仍使用旧 Pi recover/project、from-starter、pi-default 和旧能力投影。
  帮助改用现行命令和 pi-base 示例，退役语法明确拒绝；未恢复旧执行接口。
  身份/恢复/锁优先级、无 I/O、payload 不变和敏感值不回显继续覆盖。
  12 项位置 ID 完整性改验仍有效的 service_checks；另验恢复期间保留六阶段 verification
  和三项 feature_readiness，Pro held/not_ready 与运行未验分列。
- 新上游 Apache LICENSE 使用 CRLF。保持原文 SHA256
  `9a7110fc2d2f964038e5dc49128f908f29f47a574c961cba16085914e879cbda`，
  仅在 .gitattributes 为此文件声明 `-text whitespace=cr-at-eol`，不改许可证正文。

## 合入前验收检查点

| 状态 | 检查或后续工作 |
| --- | --- |
| 已完成 | 非交集字节/模式、main 来源保留和 11 项交集处理；稳定代码审阅 0 阻断；实现提交的 33 文件回归 890 passed，启动策略修订后同范围 895 passed，均 exit0；未改动的自有 Node observer 既有 7/7、exit0 证据保留 |
| 已完成 | 用户明确批准当前公开身份后的本地实现提交；批准身份指纹、暂存来源与提交后干净状态由私人授权及后置收据绑定 |
| 已完成 | 合入前文档状态、临时资源和脱敏审阅；修订后摘要的两选择六场有界原生复验 |
| 历史失败已修复 | 首次 346 passed/1 failed 为空目录；第二次 388 passed/1 failed 为退役能力测试接缝；随后单验、80 项接缝与完整 890 项均通过，原失败日志保留且不叠加计数 |
| 待必要决定 | 本轮约定交付范围内无待用户决定；Pro 与延期账号项按既有决定保持边界 |
| 失败待决策 | 无未处置的生产失败；早期控制器未证明 reload 的场次保留，完成可靠同步后另行补验 |
| 环境不足未验证 | Pro 等待合格社区上游；macOS、其他架构和真实远端机器没有本轮证据 |
| 未执行 | 新摘要下的真实模型/工具请求、外部服务查询与性能复验；原工作树这些结果保留原摘要，不作为本候选新通过 |

默认测试使用仓库与临时 HOME/XDG、假 provider/model、阻网与假进程，不启动第三方宿主。
默认沙箱的根目录属主映射不满足路径保护基线，定向回归在获准的外层执行器中保持原保护和隔离运行。
完整实际 argv、退出码、来源摘要与原始失败记录保存在私人存储，公开只报告脱敏结果。
完整定向回归包含 20 个 test_pi 文件，以及 agentcfg doctor identity/interaction、CLI environment、
home discovery、model defaults、paths、DSH optional/SSH/auto-review、deployment、runtime、
runtime preparation recovery、OMP runtime foundation 共 13 文件。参数使用
`-B -m pytest -q -rs --tb=short -x -p no:cacheprovider`，隔离临时目录及保留策略随实际 argv 记录；
pytest 报告 283.20 秒，执行器耗时 283.61 秒。测试清单摘要与运行前后正文一致。
实现提交时的公开内容检查覆盖 867 个当前文件，发现 0；当次 31 份 feature/正式 Pi 文档的
186 个本地链接有效。合入前扩大的文档/链接检查和脱敏范围单列在下节，实际暂存树与
最终后置结果由审阅材料绑定。

## 修订后源码的有界原生复验

Linux x86_64、Node 24.14.0/npm 11.9.0、官方 Pi 1.3.0；源码为上述 4aa362a6…。
正常管理器运行于受支持的外层，公开 launch 回调只包裹无路由 namespace 及验收同步，
不放宽生产参数白名单或路径保护。实际宿主 namespace 仅 lo，IPv4/IPv6 路由均为 0；
正常物理实例及 state 租约保持，当前 Pi 没有独立包 guard。

| 选择 | 实际原生命令与结果 | 来源/归属边界 |
| --- | --- | --- |
| Base | `--version`、`--help`、90×35 TUI `--no-tools --thinking off` 三场 host/manager 均 exit0；真实 reload 完成、CtrlD 退出及 termios 恢复 | 使用禁用后的默认闭包，正常重新部署新启动策略 |
| footer + cache + Context7 + browser Skill | 重选后同样三场均 exit0，真实 reload 完成、CtrlD 退出及 termios 恢复 | 组合锁 `14f845163acd43c1461b71600e4a58e9688ef06c4dcd4f5c91834e9510e24b0d`；两项 Base Skill 和 browser Skill，所选插件/MCP 准确 |

六场均核对正常受管环境已提供 `PI_OFFLINE=1`，回调环境增量为空，不靠验收回调补入该值。
TUI 只发送 `/reload` 和正常退出，不发送模型提示或工具调用。为避免将模型标签误作就绪，
使用仅 `ctx.ui.notify` 固定标记的临时公开 `session_start` observer；等标记后才提交 reload，
并实际看到官方 Reloading/Reloaded 完成。observer SHA256 为
`4d5c38dd48a4dc7f1e29068ce37b1d0655517ac9d2d9459d65e843e61b9cba52`。
原始 argv、追加 `-e` 后的 argv、namespace 包装及退出状态分别记录，不把它当作生产插件或权限保护。
没有读取真实 key、认证或会话；没有新模型请求、外部服务查询或浏览器启动。
Context7 的配置/加载和子进程释放不等于外部查询通过，browser Skill 加载不等于 Chromium 操作。

7e73… 源下的普通受管设置实际 apply 到 4、正常 rollback 回 3；禁用切回默认锁
522bed3a… 并通过 TUI。随后在空闲边界只替换自有 Pi 适配文件并校验完整 318 行来源，
以新源正常重新 apply Base、重选组合，lock/sync/plan/apply/doctor 均 exit0。
旧源重选没有另外执行，不将跨源顺序写成旧源完整闭环。MCP 共享文件来源保留、原生服务从 0
恢复 1，footer 偏好 hash 与初始组合一致，没有手改 owner、原生配置或部署状态。

早期 archive 模式误差、namespace 探针使用 sysfs 误判、在 startup 门前发送 reload 的记录
全部保留。首个探针拒绝发生于宿主 exec 前；不能把它或只看到终端回显的场次算作 reload 通过。
最终本次两实例共 17 条 owner（旧 Base 5、组合实例 12）均 complete/idle，active/unknown 为 0。

## 文档、临时资源与公开隐私

两语 README 已按来源分列实际验收，清除状态信息仍未交付的旧说法；实施及交付页中
原工作树未提交的描述保留为明确历史检查点。八份临时设计草稿的有效内容已承接正式文档，
其退出包含在实现提交中。原 reboot 工作树及来源不能确认的下载归档保留，不删除未知文件。

主 `main` 工作树原有三份未提交 DSH 文档改动单独备份，三方合并预演均无冲突，
不吸收到 Pi 提交。私人审阅目录为 0700；发现的四份 0644 审阅文件已收紧为 0600。
本轮公开检查生成的可再生 bytecode 已删除，后续检查禁写 bytecode。

仅在正常 doctor 确认已安装后，持物理 EX 及 state 锁再次核对本次 owner 完整空闲，
才回收本轮可再生成 node_modules。最后一次删除的普通文件正文为 171656371 bytes，
该阶段观察到文件系统可用空间增加 244150272 bytes。源码、锁、收据、state、原生数据和
原始失败日志保留；fixture 重用须显式 sync，清理后不沿用先前 doctor 声称依赖当前已安装。

补充隐私审阅覆盖 853 个跟踪文本文件、实现提交消息和准备的 PR 正文，命中按合成样例、
识别器、公开来源及必要法律署名分类，没有确认的真实敏感值。收尾差异和新增提交继续执行
公开内容、来源、批准身份与消息门禁。身份私下核对 name/email、仓库本地配置、作者/提交者
及环境覆盖，不在公开材料记录身份原值。真实密钥、认证、会话和原始运行日志不作为扫描输入。
范围是当前公开候选及引入 `main` 的新历史；保留的原工作树和未知来源临时材料不在删除范围内。

收尾公开内容检查覆盖 867 个当前文件，发现 0；扩大到 40 份相关文档的 244 个本地链接
全部有效，`git diff --check` 为 exit0。最终源摘要与回归输入一致；收尾提交的稳定差异、
身份、消息和实际树由最终审阅及提交后收据再次核对。

## 交付边界

任务仍为 87/96，T064–T071 和 T096 开放。Pro 继续社区路线并等待满足原约束的上游；
Brave/Cursor 真实账号验收按用户决定延后。新候选不改变这些决定，也不新增自有执行器或修改上游。
本地提交、合入、远端发布和完整 feature 归档各自保留其治理门禁。
