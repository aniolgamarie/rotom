# Base 提供者替换的实际激活边界

2026-10-11，T042–T046 继续实施。已有 capability/provider 选择与 sealed 包原语复用；不新建插件平台、执行队列或第二部署事务。

包目录的 `activate(stage, final)` 只安装/修复该 runtime identity。实际启动来源仍是原 `deployment.json.current.launch`；新包存在不表示已被选中。原 pending→受管文件→deployment 提交→recover 顺序、source→life→state 锁顺序和三方配置/账号/会话归属保持。

实现方向：现代 Pi 的替换记录置于原私有 state 区，绑定原/新 runtime、锁/slice/能力选择及配置基线，最多保存必要非秘密状态/迁移/恢复引用。记录描述 `staged → validated → activation-pending → active → retired`，失败为 `restored | recovery-required`；记录不授予激活、卸载或旧执行新绑定的能力。

`sync` 只记安装与校验事实，不标 active。`apply` 在已有生命周期保护内，先根据原无 pending 的 current 与新的原 runtime.record 确定意图；记录 activation-pending 后仍用原 deployment.apply。只有原 pending 已解决、保存的 current.launch 指向新 identity、包原校验通过时才能结算 active。失败或回执丢失按原 current/previous/pending 的实际关系对账，不猜提交，不自动重放文件部署或数据迁移。只读 status 展示保存阶段和可核对的实际 pointer 关系，不能偷偷修复状态。

`recover` 先执行原配置恢复，再在同一授权/锁边界结算替换记录。`rollback` 保持配置与 launch pointer 回滚；旧包缺失/损坏时原 run 拒绝，不把 pointer 回滚当已重装旧包或恢复数据库。迁移/格式不兼容则明确拒绝或 recovery-required；不复用同名但不等价的会话、工具或 registry。

退役与可卸载分开。`current`、`previous`、未解决 pending、活动/unknown lease、Task Keeper/Durable/委派恢复引用及必需证据都要保护；无法解释旧引用时不可卸载。由原 `assert_inactive/protected/valid_evidence` 和格式明确的原引用权威提供事实，目录 status 仅证明包完整。账号/OAuth/key、原生会话和业务数据永不因卸载删除；只删明确受管、无引用的资源。

验证目标是一组明确等价且状态格式兼容的提供者：允许/拒绝/取消/故障、安装未全、激活中断、丢回执、重复 owner、不兼容、旧任务仍绑定旧身份、配置/包/数据回退分别可核。默认用两个替身验证机制，最终用实际 Base 原生组合重验。用已有受锁部署 journal 的切点测试，不另造事务成功记录。

待最终接口决策：记录读写与原 apply/recover/rollback 的具体接缝，以及旧格式未知引用的封闭 DTO。以上保持为进行中设计，不将纯记录或安装层算为 T044/T045 完成；实现接口固定后才交单一 writer 接线。

## 已决定的接线方式

替换账本为私有侧记录，复用原生命周期保护；不扩展通用 deployment state/原生配置结构，不创建第二份配置 journal。记录与配置不能声称跨文件原子提交。管理入口在同一 source/life 保护作用域内分段取得原 state lock：读取无 pending 的原 pointer、原子写 activation-pending；调用原 deployment.apply；重新取得原 state lock，按真实 committed pointer 和原包校验结算。只有生命周期保护仍有效、原/新 identities 与实际 pointer 严格匹配才允许结算。

异常与进程崩溃都可留下 activation-pending。查询仅返回 stored phase、原 pointer 关系与阻断项；不自动改阶段或重放 apply。显式 recover 先解决原 journal，再据实际 old/new pointer 将侧记录结算为 active/restored；指针既不匹配旧也不匹配新、包/记录损坏或存在不明确的数据迁移时保持 recovery-required。恢复不用私自改写 launch pointer。通用 recover/rollback 事务仍是唯一配置变更权威。

首个实现以 Base 和明确 stateless/同格式的等价提供者为边界：跨 owner 或没有明确兼容材料不激活；不能仅凭 capability 名或 state_owner 相同宣布状态互通。Full 引用查询按其原权威接入；尚无法解释的 Task Keeper、Durable、委派或原生会话引用要报告 unknown 并拒绝卸载，不读取其库猜为空。当前/previous/pending 的旧 launch 引用均保留旧包；有效终止只允许释放 Writer，不意味着恢复/结果引用已消费。

计划验收：原安装成功但未 apply 时仍 validated；原 apply 提交前/后丢回执分别对账；同状态锁之外无私自提交；active 只与原 committed current 相符；不兼容与 protected lease 零激活；旧 previous/session/未知任务引用存在时零卸载；显式恢复不重复部署或删除用户账号。后续添加受管清理入口时需另固定引用退休/确认语义，不能以 exit/过期自动清历史。

## 首个实际接口（2026-10-11）

`pi_replacement.py` 管理严格 0600、最多 1MiB 的 `replacement.json`，只保存归属、阶段、旧/新 runtime 和非秘密 launch/提供者契约身份。正常现代 `sync` 在原 source/lifecycle guard 内写 validated；正常 `apply` 在同一 guard 内使用侧 pending→原 deployment.apply→原 committed pointer 对账；原 `rollback` 后只核对事实，不安装旧包或恢复数据。`run` 拒绝 unresolved/recovery-required 侧记录。已有无侧记录安装不自动推断跨 identity 兼容；同一 identity 可保留原启动契约并建立记录。

`./agentcfg --profile pi-base pi-maintenance status` 只读；`recover` 在原独占生命周期边界内先完成唯一配置 journal，然后对账侧记录，不重发模型/任务。`uninstall --runtime-identity HEX64` 仅删除原 backend 的 `instance/runtimes/HEX64`：current/previous/pending、活动或未知 lease、必要历史 activity、原生 session、未知任务/委派/服务存储均阻断；Full store 查询不完整时明确保护全部旧包。此首版保护策略可能暂时无法卸载保留历史的实例，不能称完整引用退休实现已完成。

兼容输入从已验证 lock 能力选择产生；同 runtime 不允许重绑另一提供者契约。无状态能力的 contract/config ownership 完全一致时允许等价提供者变源；有状态能力仅完全相同的提供者声明可沿用，变源/版本/owner 的数据格式材料未实现，固定拒绝。旧执行仍保存旧 lock/runtime，不重新绑定新包。

五模块默认最终 81 passed，包括新24项替换测试和原部署/启动/静态校验/生命周期。此前四模块63通过、宽回归59通过/1 OMP stale-lock失败，以及旧fake-sync夹具未mock新增接缝的79通过/2失败分别保留，不合并计数。全实际等价提供者组合、保留引用退休 API、安装切换原生验证仍待，因此 T042–T046 未整体签发完成。
