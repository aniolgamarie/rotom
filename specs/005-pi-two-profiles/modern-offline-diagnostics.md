# 现代profile离线诊断计划

`modern_profile_plan`只接受profile_id、现有五字段diagnostic_identity、六类显式选择与资产发现声明的缩小投影，不读取文件、来源、认证、模型、服务或证据。`pi_diagnostics.capabilities`只在现代profile的pi-host行追加profile_plan，复用已计算身份；legacy行保持。现有doctor外层仍会render、读取配置证据与写诊断缓存，`--live`仍为独立HEAD探测，不能把整个doctor称为纯函数或零I/O。

输出按kind/id排序的已选来源ID和registry分类；这里是计划，不是已加载清单或来源认证。每个来源load_evidence固定not-run，七类file/model-bash/user-bash/mcp/extension/worker/service隔离入口均未验证、complete_coverage=false。即使同身份generic pi-host native load/execution证据为verified，也不能升级这些状态或签发完整隔离结论。完整source-set与注入观察仍须后续实测。

discovery_plan范围仅assets。global/package为explicit-selection-only、ancestor为disabled、project依声明enabled/disabled，每项observed仍not-run；这些是配置意图，不证明宿主执行了排除，也不表示项目AGENTS规则关闭。外部skill只输出count，providers/auth/header/MCP正文或路径不复制。roles/skills兼容公共registry的Unicode ID，其余选择保留现有适配器ID范围；诊断另有单ID512 UTF8字节、总4096项/65536 ID字节的有界输出，超限固定失败，不截断或转写ID。

四文件一次三模块70项默认检查通过，18.75秒，稳定独立审查无P1/P2，归档`modern-offline-diagnostics/`。首次将完整resolver放入Full import poison的失败来自既有pi_web.configuration校验import，单独记录；修正后的guard只隔离新增helper/hostrow路径并使用一次identity spy，不证明整doctor零Full import。真实identity/render/EvidenceStore正控另行覆盖通用证据与计划分离。没有SDK、模型、真实账号或服务执行；T011完整实际加载、注入检查和产品gate仍未完成，正式任务7/100。
