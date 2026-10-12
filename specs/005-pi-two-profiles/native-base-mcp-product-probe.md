# Base 实际 CLI/TUI 与受管 MCP 合成组合

2026-10-11，按用户授权直接执行低风险隔离测试。所有模型、账号和 MCP 服务为自有合成输入。官方 SDK/包未修改，生产 SDK 工厂、ModelRuntime、Host、Supervisor、准入和 UI 均按正常入口执行，无 factory DI 或 SDK 方法改写。

## HTTP stage06：已观察并独立复核

材料在 `.cache/pi-two-profiles/run-20261004/base-native-mcp-product-review01/`；stage pins `58d0f1120d09ead905ddc4eb3311e831a22c2f771dbba92d7cfc1d2787860b62`。新私有来源仅增加显式合成 MCP 策略/registry/local 配置，并修自有模块解析器；锁与安装由原 `PiBackend.resolve_lock`、正常 `validate/sync/apply/doctor` 生成，不写用户环境。

外层 bwrap 断外网、系统/官方包/源码只读、仅本项私有临时账号/项目可写。真实 PTY 为45行160列，经 `agentcfg run` 启动原 TUI。仅使用公开 `/mcp` manager 菜单、真实终端输入，依次 Enable 两项服务及选择 Code Mode exposure；未调用内部连接对象或伪造 RPC UI 响应。

| 观察 | 原结果 |
| --- | --- |
| 启用之前 | 模型请求0、MCP连接0 |
| 公开 TUI Enable/Exposure | 两服务各 initialize/initialized/tools/resources/template 共5消息，模型请求0 |
| HTTP none | 原 transport 不携 Authorization，查询返回固定 own 结果 |
| HTTP bearer | 原 transport 只注入所选合成 slot，服务器核 header 精确匹配 |
| Code Mode | 两次服务查询、一项资源列表、内层失败、未声明服务拒绝；真实 session `isError=[false,false,false,true,true]` |
| 效果计数 | 合成模型HTTP10次/max_inflight1；MCP HTTP14条，tools/call恰3次；未声明服务零外发 |
| 原生命周期 | TUI 自然退出0，outer退出0/stderr0/capture_failed=false；本实例 Host leases 原 verified reclaimed/protected0，无 Writer预留 |

内层 MCP 错误的 Code Mode 文本仍可能表示脚本正常返回了失败对象；原会话外层 `isError=true` 才是本项失败传播 oracle，不凭最终合成模型文字或文本前缀认定成功。

固定 SDK 的 RPC 虽有 `ui.select`，stock MCP manager 却使用 `ui.custom`；RPC 不支持该菜单，`/mcp` 只有状态及有限认证操作，不能 Enable。因此此项使用真实 TUI/PTY，不能由旧 B12 FakeSupervisor/UI 组件结果替代。

阶段失败保留：旧 ESM import-only 包被 require resolver 拒绝，初始CLI exit5/0模型/0MCP；窄修复默认14通过并经正常producer重建后 TUI 可启动。随后探针过早输入、ESC帧相邻和缓存Footer误判均分别保存；其中一次强制清理留下旧实例未知Host，原启动guard exit4，未删或释放。新独立实例正常安装后 stage06通过；observer明确只对新实例签 protected0，旧实例unknown1仍保留。

## stdio stage02：实际调用通过，稳定独立复核已接受

固定自有 Python JSON-RPC server 经正常显式配置进入新候选，仍默认 disabled。首次真实服务外部lease已分配/启动/verified回收，stderr明确 `bwrap: Unknown option --perms`；其模型请求0，没有把菜单显示 Disable 当连接成功。

生产窄修复已默认验证：现代 bound command 由原 `host_namespace_binary` 核 sealed `bin/pi-bwrap`，private input携 path/hash，worker授权后持有原严格核验FD exec；null/错摘要/未知字段拒绝，不回退系统旧bwrap，历史路径保持。MCP最终输出收据按原Supervisor endpoint派生状态根，不使用实例配置目录。受影响Python最终17默认通过，Node12默认通过；早期两条自有测试的ELF头/外层环境误认失败保留。

正常producer和新独立实例四命令通过后，原CLI/TUI实际运行stage02：outer0/stderr0/capture_failed=false、CLI自然退出0，6次合成模型请求/max_inflight1；原session三个CodeMode `isError=[false,true,false]`，分别为查询、服务错误、资源列表。原stdio stdout protocol独立捕获恰两条query响应，成功/失败各1；完整capture/hash与原exit出生身份吻合，stderr0，无截断。原服务被控制器撤销到generation2，exit=-15属于服务关闭；原Host和external lease均verified reclaimed/current实例protected0、无Writer预留。正常模型文字不充当成功oracle。

stdio stage pins `78e683206dd38a0e31a879c6ec20f93295682fff26721c2c0f60aa1567bcf2d1`，22输入246,507B。两个此前测试实例的unknown Host继续保留，分别位于state_root/state_root02；只对新state_root03签protected0。只读observer早期source_path被后续lease循环变量覆盖的标签错误已修，最终session源路径、独立副本和SHA相符；没有重复发送服务或模型。稳定独立复核未发现本次差量 P1/P2；Root 接受收据 `e1a9873ac1263b67190137159b58ecf77fb4ee445be22303117d89cd16519679` 固定 HTTP 与 stdio 的46项输入，测试轮次保持各自身份。

此材料只签明确的私有合成输入和运行身份。真实 MCP 服务/账号、实际模型质量、OAuth/classic SSE、中途请求取消/完整故障矩阵、最新仓库两 profile 锁组合和完整产品 gate 不据此通过；T024生产实现已按固定支持契约完成；最新组合/真实服务与整个产品资格另验。
