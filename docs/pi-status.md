# Pi 状态信息与验收口径

当前默认仍为原生UI。可显式选择`pi-footer@0.5.1`及仓库公开事件观察器；来源、按选锁、
配置初始化和隔离统计契约已实现。Powerline0.20.2仍held，不能选择或入锁。
Linux本地三宽度/回环SSH、共享默认模型多轮/取消恢复/压缩统计已通过；用户已明确接受三处显示差异，十类信息交付门关闭。实际账单仍unknown，其他平台不外推。
以下区分需求口径、已实现数据与实际验证范围。

## 原栏来源与新来源边界

原栏来源为 `agents/pi/packages/colorful-footer/index.ts`。工作目录/分支来自上下文与Git状态；模型/effort来自宿主选择；token/cache/cost来自当前会话分支assistant usage汇总；context来自宿主上下文估计（旧200000回退退出）；时长来自会话起点；活动来自宿主事件；旧速度为上下文增量/时间；权限来自旧permissions/session-yolo私有接缝。后两项不能原样搬迁。旧实现及其字段存在不等于新版本有公开数据。

新组合只接受固定版本公开会话/模型/context/usage及生命周期数据，来源未确认则unknown/unavailable。字段观察须包含含义、value或unknown/unavailable、统计范围、来源、更新时间及有效性；重载/模型切换/分支/压缩时重新核对范围，不能展示过期值为当前事实。会话起点不可确认时不用进程启动时间冒充。

## 4. 十类状态栏信息的正式口径

以下是旧栏需求的承接，不是要求复用旧扩展或保留错误算法。

| 信息类 | 数据含义与首选公开来源 | 缺失/变化处理 | 显示优先级 |
| --- | --- | --- | --- |
| 提供方/模型/思考强度 | 当前宿主可公开确认的选择；请求与上游确认分列 | 切换后更新；不把桥接选择当服务端证据 | 最高，60 列仍可辨认 |
| 项目与 Git 分支 | cwd 的项目简称、公开 Git 查询 | 不显示私人绝对路径；分支改变刷新 | 中，长名可截短 |
| 输入/输出用量 | 当前会话分支的 assistant usage 累计 | 继续/切分支不重复累计；注明范围 | 中，可收拢 |
| 缓存 | 读取量与读取占比；分母为 input+cacheRead+cacheWrite | provider 未上报则 unknown；写入量可作新增显示，不冒充旧必需项 | 宽屏或二级 |
| 费用 | provider 上报或明确估算的累计费用，注明范围/币种/来源 | 订阅桥无账单值时 unknown，不把缓存率推成真实费用 | 宽屏或二级 |
| 上下文 | 当前公开 context tokens/window、比例及风险 | 模型切换/压缩后重算；未知 window 不回退猜 200000 | 最高 |
| 会话时长 | 公开可确认会话起点到当前时间 | 继续或重载须说明起点，不拿进程时长代替 | 二级 |
| 主会话活动 | 适用公开 agent 活动事件与状态 | 不单凭 turn_end 宣称 idle；与后台存活/任务成功分开 | 最高 |
| 速度 | 若可提供则说明分子、时段与算法 | 旧上下文增量/秒不叫输出 token/s；压缩等造成不可比则不显示伪精度 | 低 |
| 权限摘要 | 仅来自新组合可确认的公开权限来源 | 不继承旧 session-yolo 私有 Symbol；无来源则 unknown/不显示保护承诺 | 按可用性 |

总 token 不是 context token；累计用量不得把工具文本再算一次，子任务也不得同时合并为父用量
又单独相加。费率不明或 provider 不上报的数据不可按零填充。
旧栏没有 dirty、子代理或长命令进度，不把新增字段当作旧信息对齐的必达条件。

## 5. 布局、生命周期与公开接口

- 用 60、90、130 列作为测试宽度，不要求重现旧 70/120 断点实现。
- 最窄时优先模型/提供方/effort、主会话活动、上下文风险；统计可收拢，须能辨认或展开查看。
- 中文、宽字符、长名称、resize、SSH/tmux、输入粘贴、取消、重载和退出均须测试，
  不覆盖编辑器私有状态、不伪造终端宽度或后台存活。
- 单一界面所有者；customItems 或公开 setStatus 只提供显示接口，不能自行创造缺失数据。
- 不为显示引入隐式模型调用、无限自动 follow-up 或不必要高频 Git 轮询。
- 只初始化可由用户选择的 UI 偏好，持续受管选项逐项明确；隐藏显示不能作为关闭 hooks 的证明。

Powerline 0.20.2 当前暂停准入：没有已核实可关闭所有不允许路径的公开配置，
不进入默认/可选配方或新锁。关闭 fastRender、段显示、queue compact 模式仍不能证明合规。
将来若上游以公开接口解决，须重核精确发布包、所有注册 hooks、统计口径和交互组合。

允许阶段性交付原生 UI，并公开列出缺口；这只能完成 Base 的回退体验。
十类对照须 100% 有处置，能公开确认的信息须覆盖。未覆盖差异只有获得用户明确接受后才能
标为信息对齐完成；此计划不替用户接受缺口。Pro 和完整 feature 的验收状态与 Base 分开。

## 分层进度

T051仅完成十类映射、统计和布局意图。T053/T054审阅精确候选与公开API，T055–T057实现和隔离验证，T058分别取得原生UI与账号用量授权后验收，T059仅在覆盖全部承诺或用户明确接受差异后关闭。未确认费用、窗口、活动或权限绝不填0、idle或已保护。

## 当前可选组合：pi-footer 0.5.1

使用`plugins=["pi-footer"]`显式选择，然后lock/sync/apply；默认不加载。社区包独占setFooter
和终端布局，仓库观察器仅消费公开sessionManager.getBranch/getHeader、模型/context和生命周期
并发布`pi-footer:update-widget`；没有编辑器替换、私有状态访问或自有footer渲染。
`PI_FOOTER_CONFIG`固定到本实例extensions/pi-footer.json，配置只初始化，之后`/footer`偏好修改保留。
真正禁用须从选择中移除并显式维护，`/footer off`只隐藏显示，包的hooks仍在。

两行初始布局：第一行限长provider/model/effort、agent活动和context风险；第二行当前分支
用量/cache/估算费用后跟项目简称/Git分支。完整模型名、统计范围、时长、速度、权限和更新时间
可用`/agentcfg-status`查看；窄屏会截短第二行，用户可以`/footer`调整布局。

- 当前分支assistant使用量去重统计，不把toolResult/压缩摘要/cache_warm/子任务再相加；
  这些排除范围在完整信息中明确展示，不能把它称为整份会话的全部费用。
- 缓存分母为input+cacheRead+cacheWrite，任何必要usage缺失保持unknown。
- 费用显示host价格表估算USD；费率全零/缺失、历史模型未确认或usage无cost则unknown，不冒充真实账单。
- context来自公开估计tokens/window，未知不猜200000；模型切换/压缩事件重新取值。
- activity使用agent_start/agent_settled与公开UI prompt事件，turn_end只更新数据，不能单独变idle。
  菜单结束后优先保留嵌套prompt或working；其余只有公开isIdle()明确为true时才按待处理消息
  显示queued/idle，否则unknown。紧凑provider仅省略开头agentcfg-，完整详情保留原始路由身份。
- 会话时长仅用header起点；速度为当前分支assistant输出总量/首末assistant时间间隔的每分钟均值，
  不是实时输出token/s，单条或缺时间戳保持unknown。无公开权限来源，permission明确unknown；详情写明“宿主未提供可查询的权限状态；此项不代表权限保护。”
- 观察器无定时器、网络、文件写或进程；退出清空四个事件值。社区包自己的Git和配置UI
  仍有实际执行成本。实测启动与上下文按精确组合记录，不作性能收益或真实账单主张；其provider
  payload verbosity只读hook不被默认widgets使用。

隔离证据：`tests/test_pi_status_contract.py`/`test_pi_status_admission.py`加
`node tests/pi_status_observer.test.mjs`。Node测试只加载仓库观察代码和合成API，当前7/7通过；两份Python状态测试13项通过（11.30s）。
合成宽度检查本身只证明布局意图。

Linux本地B组以官方Pi1.3.0、theme0.1.6及footer0.5.1和修订观察器实际通过tmux3.5a
的60/90/130列中文多行bracketed粘贴、Ctrl+C清除、reload及Ctrl+D正常退出。
`/footer`菜单Ctrl+S保存enabled=false，退出菜单后显式lock/sync/apply重建，配置SHA与正文
逐字节不变，重进仍禁用；`/footer on`恢复后没有重复footer。紧凑provider显示example，
完整`/agentcfg-status`保留agentcfg-example；菜单prompt结束恢复idle，reload后完整信息及
unknown规则正常。C组缓存诊断显示waiting provider usage；隐藏后reload可再次显示，显示时
reload恢复默认隐藏且无残留。

上述首次交互为虚构绑定、合成占位key及无外网路由下的无账号检查。后续共享默认模型
调用使用正常SecretRef认证，模型工具全部关闭，未读取或向模型提供key正文。
B已验证续开/分支/reload不重复计数、多轮累加、运行中Escape后stopReason=aborted、正常恢复，
以及原生compact前后input3201/output127保持不变，后续新增请求变为3625/142，缓存53%。
压缩摘要不重复计入当前分支assistant统计；不把本地取消确认当作服务端取消或停止计费。

C真实cacheRead1280/input182时显示87.6%，与标准SDK字段公式一致；零数据等待、reload和
重新显示分别验证。B/C都正常退出、owner完整空闲。费用费率全零时保持unknown，SDK零费用
不代表免费。完整底层模型和实际账单无法由该上游路线确认，保持unknown。

A/B/C回环SSH90列粘贴/清除/reload/退出的client/manager均0；非root inetd sshd退出255
及login-record限制保留，不声称真实远端机器或其他平台已验。原任务SSH/tmux交互范围已覆盖。
用户明确接受三处差异：权限详情说明、当前分支输出均速、窄屏统计放在详情。因此T058/T059
按该范围完成，完整Pro/feature门独立。精确来源、实际运行与历史失败见
[本轮交付验收](../specs/005-rebuild-pi-toolkit/current-delivery-acceptance.md)。

权限这一项只说明可观察性。官方`--no-approve`控制项目配置/资源信任，不提供逐工具审批或
操作系统隔离；可信插件仍具有宿主进程权限。本轮真实工具测试另有显式的合成文件保护器，
不能将该测试保护器解释为生产默认能力。
