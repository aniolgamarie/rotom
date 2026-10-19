# A/B/C 无账号原生验收

日期2026-10-19，分支design/pi-toolkit-reboot。用户在明确的A/B/C无账号原生请求后答复“授权”，
随后要求“继续”。本记录覆盖该范围；不扩展为D–G、登录、模型请求或收费服务授权。
执行方案见[native-validation-plan](native-validation-plan.md)，完整feature门仍见[tasks](tasks.md)。

## 候选和执行条件

HEAD仍为`8ac50aaa8168b8a377c59736eaa1aebeb83a48c6`，目标main仍为
`93e4f7899725336c1180e53b4ec239eea5f984ce`，含未提交实现，未移动分支。
Pi官方1.3.0、主题0.1.6、Node24.14.0、npm11.9.0；Linux x86_64、tmux3.5a、script2.32.1。
没有修改宿主、社区包、vendor或二进制。两处原生发现只修改仓库自己的observer及其测试。

每组使用全新私有checkout/HOME/XDG/instance/state/空项目，0700目录、0600绑定与日志；
项目只有合成中文长分支的git init，无提交、身份配置或真实项目数据。
使用虚构provider/model；先验证空key的“无模型可用”，再用明确的合成占位key验证长中文模型标签。
该占位值不是账号凭据，不证明认证、entitlement或真实模型存在。

管理器在外层运行；仅Node/宿主child经公开unshare进入新user+net namespace，再exec原始CLI。
27次Node入口均核对namespace异于原网络、只有lo、IPv4路由0。使用私有PATH包装器，
不使用NODE_OPTIONS、预加载或宿主补丁。独立tmux socket加空配置，不连接用户已有server；
另有A的非tmux真实PTY。该隔离不是文件系统或任意Bash沙箱。

准备阶段29条管理命令全exit0，npm ignore-scripts。初始无owner、无认证、会话目录为空；
原始argv、网络身份、进程出生信息、PTY输出/时间和截图仅在私人证据保存。
以下路径一律用场景别名，公开记录不复制私人绝对路径或会话正文。

## 固定组合与身份

| 场景 | 组合 | 完整锁identity | 局部结果 |
| --- | --- | --- | --- |
| A | 官方Pi1.3.0+Catppuccin0.1.6，无外部插件/MCP | `522bed3a9815e84ad88235956fa0da8bd21625d59c9126af262659a0288396e7` | Linux本地无账号范围passed |
| B最终 | A+pi-footer0.5.1+修订observer | `e67e22a8fa6126909b928961ea106969ab2779e4f3f11966dafeb48fde9e3ec6` | 修订后Linux本地范围passed |
| C | A+cache-hit-monitor0.1.1 | `e5ad0250fdf8eaea2d35d0b138890797851aad0654b053ca812749631bbdbcc8` | Linux本地无usage范围passed |

B初始使用82f5b4ac…78c4；发现问题后完整退出，确认owner空闲，复制自有observer修订，
明确执行lock/sync/apply，三步均exit0。新recipe为
`0039723d3147760883b2cc6b0f723fc3d61d7e5f3e3b28f5ac8e7dabbe4e72ed`。
最终305个src/agents/shared/schemas/profiles文件摘要为
`39fa875a0cd6edc63f035515d8933032134afe2b92cdd6f0af24b76c20d70c1b`。
初始准备摘要086ad4b0…f183与此前250包组合属于修订前检查点；不当作新B的来源。
A/C不选择该observer，实际消费与默认锁身份不受这项未选来源变化影响。
正式仓库的默认两档锁没有被临时B/C锁替换。

## 实际入口和结果

每组实际执行管理器入口的version/help，六次均exit0，version正文均为1.3.0。
help在创建runtime及加载资源后退出；不能把它当无扩展执行或完整TUI成功的证明。
规范化argv如下，实际解释器/路径/完整参数在私人记录逐次保存：

```sh
"$native_python" -B -m agentcfg --local "$native_local" --profile pi-base run pi --cwd "$native_workspace" -- --version
"$native_python" -B -m agentcfg --local "$native_local" --profile pi-base run pi --cwd "$native_workspace" -- --help
"$native_python" -B -m agentcfg --local "$native_local" --profile pi-base run pi --cwd "$native_workspace"
```

共13次官方CLI运行：6次version/help、7次TUI启动，均正常exit0；初始B的两个功能问题单独记录如下。
所有宿主argv保持--no-mcp，无D–G入口或模型提示位置参数。交互只使用已核对的原生/已注册命令，
中文文本以bracketed paste留在编辑器，Ctrl+C清除；没有按提示提交键。

| 场景 | 实际观察 | 结果/边界 |
| --- | --- | --- |
| A资源/主题 | 官方TUI、四种Catppuccin主题可见，/settings选frappe；退出、apply后theme仍frappe | passed；不外推其他平台或外部编辑器 |
| A中文/宽度 | tmux真实60/90/130列，多行中文粘贴后Ctrl+C清除，/reload可继续；另裸PTY用stty真实切换三宽度 | passed；非合成宽度或截屏伪造 |
| B数据/宽度 | 修订后60/90/130列，核心provider/model/effort、idle/context保留；多行中文跨resize保留，Ctrl+C清除 | passed；窄屏第二行会截短项目/Git/统计，不称十类全部同屏 |
| B完整观察 | /agentcfg-status保留完整agentcfg-example身份、时间/范围、permission和缺失usage/cost/speed unknown；/reload后仍正确 | passed；本地虚构模型的context估计不证明真实服务窗口或用量 |
| B偏好 | /footer菜单关闭Enabled，Ctrl+S显示Saved；重锁/安装/部署后文件SHA逐字节一致，新运行仍disabled；/footer on显式重开 | passed；隐藏不等于卸载hooks |
| B菜单活动 | 菜单打开prompt，关闭idle；reload后单一footer无重复/残留 | 修订后passed；原始版本滞留unknown失败已保留 |
| C显示/隐藏 | /cache-hit-monitor显示waiting for provider cache usage；隐藏后widget消失 | passed；未显示伪造0%或真实缓存收益 |
| C reload/宽度 | 显示和隐藏两种状态分别reload；恢复默认隐藏，可再显示，无重复widget；130/60/90列中文排版 | passed；实际cache数据与账单not_run |
| 正常退出 | 空编辑器Ctrl+D，A/A2/B/C窗格退出码0；裸PTY退出0，恢复alternate screen/bracketed paste等终端模式 | passed；未测试运行中模型取消、强杀或宿主崩溃 |

无账号时空key会导致原生无可用模型；缺少其他公共模型scope的key会产生不匹配提示。
合成key仅让虚构主模型可选，不将这些提示或成功显示当账号认证通过。

## 两个主会话与维护保护

A同一已部署binding启动两个真实主会话，分别有独立manager/run身份：

| 阶段 | active数 | 实际apply退出码 | 结果 |
| --- | --- | --- | --- |
| 两主均活动 | 2 | 4 | 拒绝维护 |
| 第二主正常退出，第一主仍活动 | 1 | 4 | 不因一个退出清另一个owner |
| 两主均正常退出 | 0 | 0 | 完整内核后代释放后恢复维护 |

最终A6/B4/C3共13个run均idle_confirmed，observation.coverage均complete，active/unknown均0；
三组最后apply各exit0。UI的idle不替代这些OS观察，也不证明任意外部后台任务结束。
本次没有删除owner、超时清除归属、杀未知进程或降低锁/路径保护。
私有tmux server在窗格全部正常退出后关闭；留存的socket节点已由外层连接拒绝核对为stale，
未连接或终止用户已有server。

## 原生发现、修订与回归

1. 紧凑provider的agentcfg-前缀占满预算，实际显示agentcf…而难以区分。
   只在紧凑标签去前缀，完整观察保留原provider。Node先红后绿，新增原始身份/不同provider回归。
2. /footer菜单关闭后activity永久unknown。ui_prompt_end仅在公开isIdle()严格为true时
   按pending恢复queued/idle；nested prompt、running优先，无法确认仍unknown，不靠turn_end推空闲。
   Node先红后绿，最终7/7；两份Python状态契约13 passed/11.30s、exit0。

修订没有新timer、进程、文件/网络IO或私有API。B完整重锁/安装/部署后，真实菜单、完整状态、
三宽度、粘贴/取消/reload/退出均复验，偏好保留独立核对。
验证汇总曾误把socket文件存在当server仍活，修正为连接活性检查；默认沙箱禁止AF_UNIX，
外层重做后确认ECONNREFUSED、汇总exit0。该检查失败不是宿主或归属释放失败，未删除节点伪造通过。

## 尚未闭合的门

- SSH没有可用远端终端，macOS/其他架构没有执行环境，均not_run；不能用本地tmux替代SSH。
- 真实登录/模型调用、实际usage/cache/费用、真实队列和运行中取消、会话继续/分支/压缩仍not_run。
- D/E服务、F浏览器、G Cursor不在本次授权范围；原有静态/依赖证据不升级为原生通过。
- 没有性能、token节省或账单结论。Powerline和Pro仍按各自上游公开接口准入门处理。

因此T037/T058是Linux本地范围partial，T038/T059、T085–T087和T096继续开放，
任务总数仍80/96。A/B/C这次授权的可执行本地验证已完成，不重复申请同一授权。
