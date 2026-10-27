# Herdr 工作区使用说明

Rotom 的 `work` 入口把一个项目或调查上下文对应到一个 Herdr workspace，再按用途创建和找回 tab。Herdr 负责终端、布局和客户端连接；Rotom 负责已配置的项目发现、用途实例和启动交接。

**当前状态：结构化工作区已实现并有隔离测试，尚未完成本轮真实 Herdr/客户端/Agent 原生验收，也未部署或切换生产入口。** 下列流程用于理解和准备配置，不代表当前机器已经准备完成。旧版原生记录的范围见[历史实施证据](../specs/005-herdr-project-workspaces/implementation-evidence.md)，不能据此宣称本轮通过。

## 工作区、tab 和 pane

| 对象 | 用途 |
| --- | --- |
| workspace | 一个独立项目或 named 调查上下文；可包含多个 tab |
| tab | 一个用途实例所在的终端页；也可由用户手工创建 |
| pane | tab 内的实际终端；分屏会增加 pane |
| tab type | 模板里的用途定义，如 `build`、`agent`；首次使用才创建实例 |

[完整配置示例](../examples/work-structured.toml)提供两个模板。开发模板有 `shell`、`edit`、`build`、`test`、`agent` 五种用途；调查模板有 `code`、`agent`、`problem` 三种用途。进入新工作区只创建 `initial` 指定的一个默认实例：示例分别为 `shell` 和 `problem`，不会一次打开五个或三个 tab。`initial` 也可以选编辑器或 Agent，无需先放一个占位 shell。

`shell` launcher 打开普通交互 shell。`build`、`test`、`problem` 只是用途名称，实际编译、测试或调查命令由用户输入。`editor` 使用 `machine.editor`；`pi`、`dsh` 使用显式 profile；`codex` 使用已准备的独立 CLI，默认附带 `--no-daemon`。只检查当前所选 launcher 的准备情况。

## 准备和显式启用

准备仓库 Python 3.11+ 环境、官方未修改的 Herdr 和所需工具，参见[首次安装](getting-started.md)、[termcfg](termcfg.md)、[Pi](pi.md)和[DSH](dsh.md)。入口直接使用已准备的仓库环境，日常启动不安装依赖、不运行 `uv run`，也不自动部署、登录或更新宿主。

Herdr 配置由 termcfg 的可选 `herdr` 组件管理，已有配置按其计划与采用流程处理。不要覆盖冲突或停止仍在运行的旧任务来完成准备。真实加载、SSH/终端输入、布局和 Agent 会话仍需独立授权验收。

在选定私人机器文件的已有 `[machine.work]` 中显式设置：

```toml
model = "structured-v1"
```

同时配置 sources、templates 和 workspaces，见[完整示例](../examples/work-structured.toml)。示例 executable 和 `/projects`、`/cases` 路径均为占位数据，使用前替换；不要把占位配置直接作为已部署配置。未知字段和无效类型会失败。

没有 `model` 时继续使用 legacy 的 Git-only 七用途入口：`shell`、`build`、`debug`、`edit`、`pi`、`dsh`、`codex`。结构化专用字段不能混入未 opt-in 的配置。读取配置不迁移、接管或重启旧工作区，也不把 legacy metadata 自动转换为结构化身份。需要并存时明确选择各自的机器文件与 session，保留旧任务自然结束。

以下命令假设现有 Rotom 入口已在 PATH，`workstation` 是选定的私人机器配置名。也可统一使用 `work --local /config/machine.toml …`；`--machine` 与 `--local` 互斥，放在子命令之前。每次操作选择同一个配置。

## 三种配置入口

交互选择器、显式 CLI 和手工 TOML 编辑写入同一个私人配置，使用相同的严格校验。保存配置与启动工作区是分开的动作。

1. 运行 `work --machine workstation`，选择导入搜索路径、导入目录或新建 named workspace，审阅片段后保存。
2. 使用完整 CLI 参数；`--dry-run` 只预览，去掉后授权保存。
3. 手工编辑私人 TOML，或用 `work --machine workstation config edit` 编辑仅含 `machine.work` 的片段，然后执行 `config check`。编辑片段不包含其他配置或秘密字段。

```sh
work --machine workstation source add --id projects --path /projects --mode git --depth 1 --template development --dry-run
work --machine workstation source add --id projects --path /projects --mode git --depth 1 --template development
work --machine workstation project add --path /cases/current --mode directory --template investigation
work --machine workstation named add --id investigation-main --title Investigation --template investigation
work --machine workstation config check
work --machine workstation list --json
```

搜索路径保存一条发现规则，默认列举一级可见子目录，不把候选清单固化到配置。`git` 模式识别 checkout 根目录，包括 `.git` 文件形式的 worktree；`directory` 模式保留独立目录边界。导入单个 Git 项目的子目录会预览实际 checkout 根；导入 directory 不向上寻找 Git 根。导入已经存在的 worktree 不创建分支或 checkout。

来源支持 depth、隐藏目录排除、basename glob 排除和显式跟随符号链接；跟随链接也不能越出来源根。显式项目配置优先，其次采用最具体的来源。默认 Rotom 候选来自当前执行入口的可信仓库根，显示来源但不保存配置；它本身不授权 Git worktree 创建。

fzf 是可选的选择前端。未安装或不支持所需能力时，使用完整 CLI 与手工配置；`work` 不自动安装它。选择器清除调用者的 `FZF_*` 选项，不把候选路径作为 shell 动作、预览命令或快捷键脚本执行。

## 进入项目或 named 上下文

```sh
work --machine workstation enter /projects/kernel
work --machine workstation enter /cases/current
work --machine workstation named enter investigation-main
```

项目必须是配置来源覆盖或显式登记的现存目录。不同 checkout 各自拥有 workspace，即使共享 Git common directory 或分支；directory 项目可以独立于其外层仓库。

named workspace 只需要稳定的 ASCII ID 和标题，不要求绑定目录或题目。省略 `start_path` 时，首次进入捕获调用者 HOME 作为起始目录；后续换 HOME 不改变已绑定起点。可以显式指定现存 `--start-path`。两个 named ID 即使起点相同也互不合并。`named rename ID --title TITLE` 保存标题并尝试更新已核验的原生展示；更新失败会保留已保存标题并报告待同步，不重新建工作区。

外部进入使用普通 SSH shell，先离开旧 tmux。内部进入只切换焦点，不移动发起命令的 shell。请在目标工作区中可输入命令的 shell 运行用途管理命令，避免向正在运行的编辑器、编译或 Agent 输入它们。

## 默认实例、额外实例和固定目录

```sh
work --machine workstation open build
work --machine workstation open build --new
work --machine workstation open
```

普通 `open TYPE` 聚焦已核验的默认实例；没有默认实例时才创建。`--new` 每次都创建 extra，**即使尚无默认实例也不会成为默认实例**。以后普通 `open TYPE` 仍创建或聚焦默认实例，不提升 extra。无 TYPE 的 `open` 提供用途、已记录实例和重绑定选项；Herdr 原生导航也可找回手工终端及额外实例。

每个类型首次实例化后固定 cwd、捕获 HOME 和相关 launcher 契约。省略 cwd 等价于：

```toml
cwd = { from = "workspace_start" }
```

`workspace_start` 是首次绑定的工作区起点，不随 tab 内后续 `cd`、调用者 PWD 或标题变化。`cwd = { path = "build" }` 相对此起点；`~/…` 相对捕获 HOME；绝对路径也可使用。目标必须是现存目录，不自动创建、不执行 shell 展开。不同 cwd 形式不能混用。

聚焦只切换焦点，不注入命令、不重启程序、不改运行中的 cwd。配置漂移时原有可核验默认实例仍可聚焦，矛盾的新建被拒绝。已删类型的已绑定默认实例仍可按原 key 找回，但不能据此创建 extra。

从配置中移除用途后，普通选择器只保留其已有实例，并标注 `Removed type: focus only`；它不会出现在 `open --new` 的新建列表中，也不提供重绑定选项。没有已有实例时，该用途不再出现在选择器中。聚焦前仍会验证目标是否属于当前工作区。

只有确认该类型在当前工作区无活动实例且没有未决交接时，才可显式重绑定。交互入口先展示新契约并确认；非交互使用 `work --machine workstation rebind TYPE --accept`。它不关闭进程，也不把未知状态当作零活动。

## 新建 Git worktree

选择器有独立的 New Git worktree 表单：选择已登记 Git 项目、目标、模板、新分支和显式本地 base，再审阅。命令行示例：

```sh
work --machine workstation worktree create --repo /projects/kernel --path /projects/kernel-fix --template development --new-branch fix-example --base refs/heads/main --dry-run
work --machine workstation worktree create --repo /projects/kernel --path /projects/kernel-fix --template development --new-branch fix-example --base refs/heads/main
```

默认只创建 checkout。明确加 `--enter` 才在 Git 成功后进入普通独立工作区；进入失败保留 checkout，并提示单独 `enter` 重试。已有 checkout 始终可通过 project/source 导入。

交互表单会在最终确认前显示分支、base、解析后的 commit、目标和模板，以及覆盖目标的搜索规则、仓库/common 目录身份和配置摘要。确认的是这次预览的事实；若期间发生变化，创建前的复核仍会要求重新审阅或拒绝。

目标必须不存在、父目录必须已存在，并受当前可见 Git source 的 depth/隐藏/排除规则覆盖。未覆盖时，交互表单可单独审阅并保存父搜索来源，再读取新配置重新预览创建。此保存单独确认；之后取消创建仍保留先前保存，不登记不存在的未来项目。

新分支模式需要明确本地 base，预览冻结解析后的 commit。创建前重新核对配置、引用、目标和来源；变化要求重新审阅。不会 fetch、stash、复制 dirty 文件、重置原目录、初始化子模块、安装依赖或启动服务。调用禁用 hooks/fsmonitor/remote guessing；存在可执行 checkout filter 的组合会在派发前拒绝。原目录 dirty 内容、index 和持久 Git config 保留。

**当前已有分支创建能力不可用：** `--existing-branch` 可以只读预览，实际创建退出 5。已知短分支名在派发瞬间被外部删除后，Git 仍可能从 remote-tracking ref 新建分支，`--no-guess-remote` 无法提供所需原子保证；本轮将此模式列为 unsupported，不宣称两种模式均已成功。未来启用须先取得公开接口的原子保护并经过显式审阅。

失败、超时或响应丢失可能已留下分支/checkout；保留现场和记录，不自动删除或盲目重试。查看 `status` / `reconcile` 的只读结果，不能把只读查询当作回滚或重新执行。

## 断开、收起和关闭

| 操作 | 含义 |
| --- | --- |
| detach | 断开当前客户端；server 与任务继续运行 |
| 收起或折叠展示 | 原生界面操作；不表示进程已经结束 |
| 关闭 workspace | 会影响该 workspace 的所有 tab/pane 及其他查看者，属于破坏性操作 |

当前 `work close --dry-run` 能预览当前工作区范围及所有 tab/pane，包括未按用途登记的成员。CLI 的授权形式为 `close --scope TOKEN --yes`，但**当前原生公开协议缺少原子成员保护，实际关闭明确退出 5**。scope token 只绑定审阅范围，不等于 native guard；本轮没有完成或宣称全项目关闭成功。不要用 detach、折叠或预览成功替代关闭完成的判断。

## Maintenance workflow 的位置恢复

本节位置恢复已通过最终十二组无 trace 原生验收，仅开放[六个精确 Linux managed 组合的两种位置](rotom-pane-capabilities.md#本轮精确组合验收清单)。DSH/Pi 的 V1/V2 work Agent 入口四项也已正式通过；OMP 无默认 work type，经新标签页恢复建立 resident 后可原位恢复。不以历史 workspace 测试代替本次验收。

Rotom Herdr V1/V2 新 DSH/Pi Agent 入口与符合驻留组合的新 tab 恢复可使用薄驻留 launcher；普通 rotom run 不驻留。Agent 与相关后代完整退出并结束单次租约后才 parked，等待明确恢复请求，不保留 Agent 运行包或凭据环境。launcher/pane 丢失、位置复用或源码身份变化时拒绝原位恢复，旧普通实例不自动升级。

只有已停止且完成 setup/update 的完整 maintenance workflow 可选择 --original/--new-tab；普通 --session 位置请求不开放。默认 here 与停止清单的只读 --list 不需要 Herdr。单项与批量接口示例（ID 须换为完整32位小写十六进制值）：

```sh
./rotom --no-input resume pi --profile pi-base --stopped --batch BATCH_ID --run RUN_ID --new-tab --format json
./rotom --no-input resume pi --profile pi-base --stopped --batch BATCH_ID --all --original --format json
```

V1 的 caller 在 accepted 前最后核验并保存；accepted 后父进程可正常清除 workspace pending，驻留包装使用保存的 caller，不因这次清除退回普通 shell。resident 仍重核实时终端身份，不能借 accepted 或清 pending 扩大许可。驻留 parent 在 child 存活时不读 owner/Domain；退出后才核验唯一出生身份及完整释放。active 位置的 child/manager 关联只是只读候选，原位仍须 parked 与保存的精确旧 run。

新 tab 使用公开 tab.create 和专用恢复 payload；先持久化原 workflow 意图，再单次创建，ready/committed/handoff 和 child 执行事实分别核验。可能已经创建时只读查账，不重发、不向 pane 发送命令。批量先核验整批，逐项重查，首个失败或未知后停止，余项 not_dispatched，保留前面事实。加载仍待确认，零继续，Pi Pro 委派不在范围；pi-pro 普通 profile 兼容性保留。详细条件见[维护指南](tool-maintenance-workflows.md)和[位置能力说明](rotom-pane-capabilities.md)。

## 未知结果与支持边界

`work status --json`、`work reconcile --json` 和 `work list --live --json` 提供只读观察。metadata 丢失、ID 重用、成员变化或交接结果不明保持 unknown；private 记录与原生标记需要共同核验，任何一方都不能独自授权。创建可能已派发后不重发。不要手工删除 pending 来假定 launcher 已取消。

断线后重新选择相同配置与上下文，可接回仍存活的 server。机器重启或 server 退出后的布局恢复不证明原进程恢复，不自动重放编译、任务或 Agent 会话。旧 tmux/legacy 任务继续由原入口管理，不自动接管。

常用退出码：2 参数或配置错误；4 所有权冲突、未决或部分结果；5 缺依赖、公开能力不足或原生检查失败；6 文件系统失败。成功交接不证明 Agent 登录或业务任务完成。

更详细的交互与边界见[交互流程](design/configurable-workspaces-interactions.md)和[设计说明](design/configurable-workspaces.md)。Herdr 升级与旧配置恢复见[升级说明](herdr-upgrades.md)。本轮真实 native 验收、客户端组合与部署必须另记，隔离测试不能替代这些证据。
