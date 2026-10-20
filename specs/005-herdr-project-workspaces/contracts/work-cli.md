# work CLI and native interaction contract

本接口已实现，首轮目标Linux；隔离检查与未完成的原生验收分别记录。只提供项目入口和稳定用途，原生Herdr继续管理布局/导航/手工终端。

## Syntax and results

```text
work [--machine NAME | --local FILE] enter PATH
work [--machine NAME | --local FILE] open ROLE [--new]
work --help
```

ROLE严格为shell/edit/build/debug/pi/codex/dsh；未知参数退出2。enter路径必填，可相对当前目录，必须是现存Git目录。open无cwd参数，不收命令文本/Agent提示词。机器字段见[configuration](configuration.md)。

成功stdout简述动作/role；失败stderr给稳定错误码与下一步，不输出秘密/会话/私人配置正文。0/2/3/4/5/6沿用工程语义，exec原生attach或业务程序后保留其退出码。open的0只代表创建/聚焦及启动交接确认，不证明应用登录或任务成功；异步应用错误显示于新pane，不混成父work退出。

## enter

1. 先验证参数、普通配置、Git真实checkout。非Git退出2并提示原生临时工作区，零server启动/修改；路径字面不经shell求值。
2. 处于tmux且未确认Herdr时退出4，指导普通SSH/显式离开旧复用器，不自动detach/嵌套；其他native session不匹配或不明也报4。
3. 每UID固定flock内以官方herdr session list --json定位session；确实不存在才可独立启动herdr --session NAME server，准备PATH并以umask 077启动，使socket父目录保持0700、server不随发起shell退出。连接错误不能当不存在；现有server不重启。
4. 公开API ping/schema确认ready后固定endpoint；先查workspace.list/get的原生provenance。仅目标尚未打开时查询worktree.list(cwd=ROOT)，确认目标checkout唯一存在，以返回的source.repo_root作为SOURCE，调用worktree.open(cwd=SOURCE,path=ROOT,focus=false)。linked checkout仍是项目身份；完成归属核验后才focus，不创建branch/worktree，不自动trust未知仓库；trust失败明确报告。
5. 用workspace.list/get返回的原生worktree provenance确认唯一canonical checkout/workspace，并复核创建结果的初始pane，按[data-model](../data-model.md)初始化或保留用途；已有pending先按下述runbook只读核对，只有完整证明failed/accepted才能完成登记。丢响应先只读对账，不明报4，不重发创建；不预启动editor/Agent。
6. 内部仅focus；外部确认后exec herdr session attach NAME。attach前复核socket仍是固定endpoint；变化时不能连接替换实例。attach无管理时限，不是跨API事务；同时停止导致attach失败需明确记录。

同server共享活动workspace/尺寸协调。cd/branch不改项目归属；原生tab/分屏不自动成为受管用途。内部enter只切焦点，不移动发起命令的shell；不要把同一旧shell中串行的enter与open理解为改写其项目上下文，open始终验证实际调用pane。

## open context and reuse

HERDR_PANE_ID仅为待验证locator；必须在所选固定endpoint显式pane.current(caller_pane_id=ID)，根据当前成员和worktree provenance确认项目。不能以HERDR_WORKSPACE_ID、cwd、最近项目、全局active或标题替代。缺失/过期/跨session/未知epoch报4并指导enter；--new同样拒绝，零创建/启动/attach。

primary必须同时匹配workspace/project/epoch/role/op/kind及唯一当前成员，且Rotom交接phase=accepted、commit=op；初始原生shell由父调用写同样完整标记。仅focus明确目标，前后重查；不send_text/send_keys/send_input、不cd、不重启、不按idle判断。原生并发移动/关闭不受本锁保护，变化即冲突，不自动提升extra。未决pending阻止任何新创建，包括--new；不覆盖、自动清除或超时回收。已确认primary仍可只聚焦。冷恢复无pending时，unknown角色的显式--new规则保持有效。

登记后exec失败也必须可见：后续查询phase=failed或commit不符/缺失时，将该role保守转unknown并报4，保留失败后普通shell；只有显式--new建立新primary，不自动重试工具。交接phase不取自Agent任务状态，不能借此判任务完成或关闭终端。

## New tab protocol

先验证依赖，缺准备退出5或配置错误2，不先建空Agent tab。仅tab.create(cwd=checkout,label=role,focus=false)，额外实例可加显示序号；不向旧pane发送启动输入。

ROTOM_WORK_LAUNCH_V1为序列化UTF-8 JSON，最大16384 bytes，严格字段：

- version=1；role；kind=primary|extra；op/epoch各32位hex；project_digest为64位hex。
- checkout完整canonical目录、workspace_id、原machine或local选择（恰好一个）。
- session、socket_path、endpoint_dev/endpoint_ino；rotom_root/source_digest用于入口来源验证；selection_digest绑定解析后的local配置路径与七项普通启动选择，不摘要秘密。
- expires_at_ns为正整数的同机单调绝对deadline。

无秘密、会话内容或任意command/argv；超长/控制字符创建前报2，不截断。payload只用于新tab，不写native持久state。launcher重建固定允许argv，等父提交才exec。父对ready实际pane核对project/epoch/op/成员；多匹配或无匹配不猜。

launcher用自身HERDR_PANE_ID、相同socket dev/inode固定端点，验证pending后写ready；父写rw_commit=op；launcher再验证pending/commit/期限，写accepted、消费payload并exec；父见accepted后同patch设primary（若适用）并clear pending。extra保留既有primary。marker只是交接。commit不明只读查至deadline，不再发启动；不明报4。若后续完整证明同op commit/accepted且成员相符，可完成原登记再判定--new为extra，不能再exec。失败明确报错并尝试在额外最多2秒内写failed/清commit；确认失败标记后退普通shell，绝不重放。accepted请求可能已生效且失败标记无法确认时退出launcher，不留伪有效普通shell。该失败上报不延长业务exec准入deadline。重读pending不能原子取消已开始握手的launcher。详见[data-model](../data-model.md)。

## Native adapter and deadlines

发现/启动/外部attach使用官方CLI参数数组。查询/变更使用官方JSON Socket API，以herdr api schema --json和tag fixture核对协议；仅实现ping、worktree.list/open、workspace.list/get/focus/report_metadata、tab.create/get/focus、pane.current/list/get/focus/report_metadata及必要snapshot读取，不实现send-input/Agent prompt/server stop/任务wait。

socket来自公开session list，不猜内部路径；O_PATH保留已验证inode，每次请求连proc fd。每连接一请求一响应，id只做关联，不当幂等键。协议/能力不明或畸形/超长响应失败5；原生附加字段按候选审核schema处理，本地配置仍未知字段失败。升级更新公开fixture和受影响测试，不硬编码version==0.9.5。

enter及shell/edit/build/debug/codex操作总deadline30秒；受管pi/dsh open因父调用与launcher均需完整校验运行包，总deadline60秒。等锁仍最多10秒、connect2秒、单request5秒，均裁到剩余总预算。payload继承同一个绝对期限，launcher不重新获得60秒。无副作用read可在固定endpoint按剩余时间重查；mutation超时不重发，unknown/4；发送前依赖失败5，文件系统错误6。锁始终释放，运行任务不随调用返回被终止。

无新daemon、终端数据库、项目扫描/任务猜测、启动联网或安装。状态增强不是前置；work不读Avalon Review状态或自动广播。

## Pending recovery runbook

本节是已实现入口的人工恢复指南；隔离合成server的主动停止/冷恢复已验证，真实任务停服仍须确认工作自然结束并有对应授权。native查询先按显式session/ID执行，不读取终端正文；ID取当前权威查询，不按名称猜测：

```text
herdr --session NAME workspace get WORKSPACE_ID
herdr --session NAME pane list --workspace WORKSPACE_ID
herdr --session NAME pane get PANE_ID
work enter CHECKOUT
```

1. 保留新pane和其他工作，不重复create/发送启动/清token。等待本次操作deadline后，重新enter；enter在锁/固定endpoint内只读核对同project/epoch/op的唯一成员。
2. 明确failed且commit已清：launcher已进入不可逆失败分支，只能回普通shell；enter保留原角色状态并clear该已解决pending。明确accepted且commit匹配：enter完成已有结果登记，不再exec。多匹配/矛盾/缺标记/不完整查询均不解锁。手工重跑同用途不能被当成原op成功。
3. 仍未知则继续4；用户可原生Goto或新建普通tab继续项目。不得手动把未知pending清掉后假设旧launcher已取消，也不自动关闭任何pane。
4. 若原生事实始终无法重建，待该server所有工作自然结束；由用户确认已无存量任务并明确授权停服后，在Herdr外部执行原生 `herdr session stop NAME`，确认原endpoint已停止，再运行 `work enter CHECKOUT`。冷恢复布局的用途为unknown，用 `work open ROLE --new`明确新增。停服不是日常入口的自动恢复动作，也不能恢复之前的进程；若尚有任务则保留server并继续原生导航。

这给出安全可执行的延迟恢复，不承诺公开API不足时还能无损即时清除任意pending。实现与测试必须同时覆盖failed登记、accepted登记、持续未知不清除以及冷恢复的不同结果。
