# Pi 会话切换前的 Git 状态检查

`dirty-repo-guard` 在新建、切换或分叉会话前检查显式配置的 Git 工作树。扩展通过 agentcfg supervisor 执行固定 Git 状态命令，使用已有 `pi-subagents` manager，不再直接调用 `pi.exec`。

## 配置

下面是私人 `local.toml` 的配置片段。把项目根和 Git 可执行文件替换为当前机器的真实绑定；`version` 应登记实际版本。`extensions` 数组会整体替换，应合并已有选择。

```toml
[overrides.profiles.pi-default.agent_options.resources]
extensions = ["dirty-repo-guard"]

[overrides.profiles.pi-default.agent_options.paths.roots.project]
path = "/absolute/path/to/checkout"
purpose = "project"

[overrides.profiles.pi-default.agent_options.dirty_repo_guard]
tool_ref = "git"

[overrides.profiles.pi-default.agent_options.external_tools.git]
executable = "/absolute/path/to/git"
version = "YOUR_GIT_VERSION"
args = []
project_root = "project"
read_roots = ["project"]
write_roots = []
timeout_seconds = 20
```

同时需要选择 `pi-subagents`，并在配置来源中所选 Permission Policy 的 `rules` 内加入显式命令授权，例如：

```json
{
  "id": "git-status",
  "kind": "command",
  "effect": "allow",
  "command_ref": "tool:git",
  "tool_ids": ["bash"],
  "operations": ["execute"]
}
```

配置应修改来源中的策略声明，不要编辑生成的 `agentcfg-manifest.json`。选择扩展不会自动授权 Git，也不会修改现有 deny。绑定必须只读、无自定义参数、非交互；状态参数由专用入口固定。普通 bash/editor 命令仍然保留原来的 `.git` 隔离。

## 行为

| 结果 | 会话操作 |
|---|---|
| 仓库干净 | 允许 |
| 有未提交或未跟踪文件 | UI 明确选择“继续”后允许；关闭选择框或无 UI 时取消 |
| 声明范围内的目录不是 Git 工作树，且祖先不存在 Git 标记 | 允许，不启动 Git |
| Git 缺失、标记损坏、权限不足、超时、输出截断、stderr 警告或终止状态未知 | 取消，不当作干净仓库 |
| 有其他受管写操作或未收取的受控任务结果 | 取消，先完成或收取当前操作 |

项目根必须是实际 worktree 根；在其子目录启动会检查整个 worktree。嵌套仓库、把仓库的子目录误配为项目根、指向损坏 Git 元数据的标记均不会被静默当作非仓库。

普通 checkout 与可核验的 linked worktree 都支持准入。linked worktree 的专属 Git 目录和 common directory 作为只读元数据显式挂载，启动前重新核验目录和工作区身份。

检查与受管写操作共享跨实例工作区租约，命令结束还需退出记录、捕获输出摘要与独立物理终止证明。工作树及 Git 元数据只读，网络禁用；关闭 Git optional locks、fsmonitor、hooks 和自动对象获取，不读取用户或系统 Git 配置。项目自己的 Git 配置仍参与 Git 语义，依赖的过滤器或外部对象路径若不在声明的沙箱范围内，可能导致检查失败。失败会取消切换。

完整状态检查需要完整的声明范围。若机器或文件策略拒绝工作树或必要 Git 元数据的任何子路径，检查明确拒绝，不隐藏该路径后报告“干净”。可保留这些 deny 并不选择该扩展；代码快照仍可单独配置更小的范围。

检查采用 `git status --porcelain=v1 -z --untracked-files=all --ignore-submodules=none`。文件名按 NUL 分隔；重命名计一个变更项，文件名中的换行不影响计数。结果遵循 Git status 的索引、ignore 和稀疏工作区语义；不是任意外部文件写入的监控器。

## 验证范围

当前通过隔离 Python/Node mock 与扩展类型检查。未运行真实 Git 沙箱或真实 Pi 会话；目标平台加载、过滤器/子模块组合与真实终止行为仍需独立 native 验证。

隔离验证详情见 [Git 状态检查验证记录](acceptance/pi-git-status-mock.md)。
