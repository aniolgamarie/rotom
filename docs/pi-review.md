# Pi 交互式代码审查与编辑器

`pi-slopchop` 保留差异、上次提交、完整文件视图、子模块视图、快捷标注和反馈提示。当前派生版本是 `0.10.1-agentcfg.1`，完整来源与 MIT 许可证进入四个配方的源码闭包。最终运行锁和原生 UI 验收仍待完成。

## 显式绑定

在目标 profile 的 `plugins` 数组中选择 `pi-slopchop`、`pi-subagents` 和 `pi-permissions`，同时保留原有需要的插件。下面片段写入私人 `local.toml`；替换项目、Git、编辑器的真实路径与版本。

```toml
[overrides.profiles.pi-default.agent_options.paths.roots.project]
path = "/absolute/path/to/checkout"
purpose = "project"

[overrides.profiles.pi-default.agent_options.slopchop]
git_tool_ref = "review-git"
editor_tool_ref = "review-editor"

[overrides.profiles.pi-default.agent_options.external_tools.review-git]
executable = "/absolute/path/to/git"
version = "YOUR_GIT_VERSION"
args = []
project_root = "project"
read_roots = ["project"]
write_roots = []
timeout_seconds = 30

[overrides.profiles.pi-default.agent_options.external_tools.review-editor]
executable = "/absolute/path/to/nvim"
version = "YOUR_NVIM_VERSION"
args = ["--clean", "+{line}", "--", "{path}"]
project_root = "project"
read_roots = ["project"]
write_roots = ["project"]
interactive = true
timeout_seconds = 1800
```

Git 绑定必须无自定义参数、只读且非交互。专用接口生成固定审查参数；Git 名称列表按 NUL 分隔，保留含换行、空格和 Unicode 的文件名。禁用 hooks、外部 diff/textconv、fsmonitor、全局配置及自动对象下载。

编辑器绑定可省略；选择编辑操作时会明确报告未绑定。参数支持一个独立的 `{path}` 和可选 `{line}` / `+{line}`，文件参数前必须有 `--`。不读取环境中的 EDITOR，不拼接 shell 命令。示例的 `--clean` 属于 Neovim 参数；选择其他编辑器时需要声明相应的隔离参数。

在所选 Permission Policy 的来源中同时声明命令授权，例如：

```json
[
  {"id":"review-git","kind":"command","effect":"allow","command_ref":"tool:review-git","tool_ids":["bash"],"operations":["execute"]},
  {"id":"review-editor","kind":"command","effect":"allow","command_ref":"tool:review-editor","tool_ids":["editor"],"operations":["execute"]}
]
```

审查正文仍需文件读取规则。已有文件拒绝规则和角色上限继续生效；不能编辑生成的 manifest 来扩大授权。

## 工作区和终端行为

审查查询与编辑器统一取得跨实例工作区租约。有活动候选、其他 writer 或未知终止状态时，操作拒绝。嵌套仓库同时保护父子工作区；只读子模块访问必须核验其 Git 元数据确实位于声明父仓库的 modules 目录内。

编辑器的写入范围是 `write_roots` 声明的范围，打开某一个文件不会把编辑器限制成只能修改该文件。应按预期设置授权根；不允许写入 `.git`、受保护状态或已拒绝路径。编辑器网络关闭，使用私人 HOME；用户全局编辑器配置不自动加载。

交互式编辑器取得监督者创建的私人 PTY，输入、屏幕输出和窗口大小经过控制接口传递。执行许可下达后才取得控制终端。输出丢失、输入无法确认或终止未知时不能报告成功。取消请求后仍须等待物理终止证明才释放工作区保护。

快捷键和标注配置来自 `agent_options.slopchop.shortcuts`，不读取旧 `~/.pi` 或项目内 `slopchop.json`。格式和快捷键冲突会明确失败。

## 已有验证和局限

已完成完整插件 TypeScript 类型检查、确定性归档检查，以及隔离的 Git/文件/编辑器准入、PTY 转发与执行闸门测试。没有启动真实 Pi、Git 沙箱或编辑器；macOS 终端规则仅验证了生成内容。真实键盘、终端刷新、子模块组合与各平台进程终止行为仍需原生验收。
