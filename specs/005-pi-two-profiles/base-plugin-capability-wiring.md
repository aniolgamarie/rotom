# Base 插件能力与模型工具接线

现代插件声明显式区分用户选择 ID 与安装能力 ID：`pi-todo → todo`、`loop-guard → loop-protection`、`colorful-footer → footer`。Base 的 Todo 声明 `model_tools = ["todo"]`，另两项为空。渲染保留原 `manifest.plugins`，只在现代 profile 增加封闭的 `plugin_capabilities` 公共声明。旧插件 schema 兼容可选字段，旧 profile 不增加该投影。

现代资源选择要求映射键集等于所选插件，拒绝缺失/未知字段、非法名称与类型、重复能力或工具，每插件最多 64 个工具。空插件现代 mock 可缺少映射；非空选择不能回退到 plugin ID 等于 capability ID。资源仍由原安装能力所有权与原路径/内容核验选择。

会话只读取公开 `resourceLoader.getExtensions().extensions` 与 `Extension.tools`。显式工具必须由对应能力且确实所选的运行包扩展拥有，Map key 等于 `RegisteredTool.definition.name`，execute 可调用。同名跨扩展与自有受管工具冲突均拒绝。仅这些验证后的名字加入 SDK `options.tools`；`customTools` 仍只有仓库自有受管 definitions。Todo 不被复制包装，也不获得业务 Writer 权限。

每次配置快照重读公开 getter，复核所选路径、原 RegisteredTool、definition 和 execute 引用；丢失、重绑、跨来源碰撞阻断旧准入。工厂冻结其 manifest 声明，调用者事后修改原对象不能扩大当前工厂。显式映射包含在 effectiveConfigDigest/ConfigIdentity 中，即使 UI 禁用工具且 activeTools 子集相同，声明变化仍改变配置身份。工具参数、函数和原 definition 不进入摘要或深复制。RuntimeIdentity 保持原安装身份。

默认离线验收仅使用真实 catalog/resolve/render、实际当前来源声明的所有权投影与公开 SDK 替身。Node 保持固定 Node24、原 bwrap/临时 HOME/阻网与假进程 guards；未导入或启动官方 SDK、宿主或模型。正式锁仍为 candidate，官方运行与 native/账号资格待独立验收。本包不宣称 Base/Full 产品全部完成。

证据：`.cache/pi-two-profiles/run-20261004/base-plugin-capability-wiring-review01/`。最终 Python 33 passed，Node 131 passed，实际退出码均 0。
