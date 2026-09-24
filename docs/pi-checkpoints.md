# Pi 代码恢复点

`git-checkpoint` 扩展现在使用当前 agentcfg 实例中的持久代码快照。它恢复明确范围内的普通文件内容和权限位，不切换 Git 分支、不恢复 Git 索引，也不调用 `git stash` 或项目 Git filter。

## 配置

在私人 local.toml 中选择扩展并声明范围。资源数组会整体替换，下面的例子应与已有 extensions 选择合并后填写：

```toml
[overrides.profiles.pi-default.agent_options.resources]
extensions = ["git-checkpoint"]

[overrides.profiles.pi-default.agent_options.checkpoints]
paths = ["src", "tests"]
max_files = 2000
max_bytes = 33554432
max_checkpoints = 100
```

还需要：

- 已选择 `pi-subagents`，用于既有 manager 的同一队列。
- `agent_options.paths.roots` 中有明确的业务项目根，cwd 属于它，且能核验 Git worktree 身份。
- 所选 FilePolicy 在这些路径上允许 `ls/list` 与 `read/read`；恢复还需 `write/write`、新文件的 `write/create`、删除文件的 `edit/delete`。父 deny、只读根和秘密根仍生效。

选择扩展不会自动修改默认 deny 策略。缺少权限的动作会失败；例如没有 delete 权限时，涉及删除的整次恢复会在修改文件前被拒绝。

## 使用

- 每次 `turn_start` 尝试保存当前范围的代码恢复点，关联当时的会话叶节点；`agent_end` 不再清空恢复点。
- `/checkpoint` 手动保存当前状态。
- `/checkpoint-restore` 列出当前会话、工作区及权限范围的恢复点；也可输入 `/checkpoint-restore 完整ID`。
- 从带恢复点的节点分叉时，UI展示将写入和删除的文件数量；只有明确选择恢复才执行。无UI时不自动恢复。

预览后如果文件已改变，恢复拒绝并要求重新预览。执行前会保存恢复前备份；中途失败报告 `partial` 并取消该次分叉，不显示“恢复成功”。可用备份ID重新预览并恢复。

捕获、恢复都要取得跨实例的同一 worktree 租约；其他 writer 或未知执行未结束时无法开始。最终结果还需helper退出记录和独立物理终止证明，取消回执不作为完成证据。

## 范围与存储

- 只处理配置范围内、当前策略允许的普通单链接文件；包括符合条件的未跟踪文件。
- `.git`、`.ssh`、`.pi`、`.codex`、`auth.json`、`.env` 与 `.env.*` 在读取正文前排除；其他秘密目录应通过父策略或机器根明确拒绝。
- 每文件最多1MiB；文件数、总字节超限会失败，不截断后声称完整。目录、symlink和特殊文件不会被当作普通文件恢复；空目录结构不作为快照内容。
- 恢复只处理文件；范围中目标没有、当前新增的文件需要删除权限。Git索引、分支及范围外文件不在恢复目标内。
- 快照元数据与文件正文分开保存于实例的 `pi-home/checkpoints/`，私人权限保存，不进入公共配置、通用日志或同步来源。
- 会话、项目/目录身份、策略、范围和运行包必须匹配；不自动把其他项目、会话或旧运行包的快照当作当前恢复点。主题与存储配额调整不会使同一文件范围失效。
- 达到 `max_checkpoints` 后拒绝新增，不自动删除历史。可以在配置来源调整限额；原始数据保留，当前没有自动清理命令。

## 与旧实现的区别

旧扩展用 `git stash create/apply`，仅内存保存引用，并在agent结束时清空。新实现改为持久代码快照，增加权限过滤、恢复预览、恢复前备份和部分失败处理；它不是Git stash的格式或合并算法兼容层。

迁移不会读取或转换旧stash，也不会删除原仓库记录。需要Git原生合并/索引操作时，应使用明确授权的Git操作；本扩展不冒充完成这些动作。

当前通过隔离mock验证，真实Pi事件时序与目标平台加载仍待独立native验证。
