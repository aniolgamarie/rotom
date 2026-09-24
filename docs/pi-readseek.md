# ReadSeek 迁移进度与执行边界

ReadSeek 派生来源、监督控制器及固定视觉资产已登记四配方，T086 的代码与 mock 工作已完成。
完整迁移仍在进行，原生运行和发布验收尚未完成。
当前源码和隔离测试不能作为 Pi 或 ReadSeek 原生验收通过的证据。

## 已实现的边界

- 父会话保留原有九工具的参数、说明和结果渲染；执行入口转给 agentcfg。
  控制器缺失时明确失败，不能回到原始文件 IO。`overrideTools` 固定为空，
  不替换普通工具或 Task Keeper 的 `tk_*` 工具。
- worker 只接收固定工具名、显式参数、私人文件副本、缓存目录和原生程序路径。
  它使用假 Pi 注册接口加载工具定义，不创建第二个 Pi 会话。
- 文件副本只包含当前 FilePolicy 允许读取的文件。原始业务目录、Git 元数据、
  全局账号和设置不作为 worker 的隐式输入。
- 计算产物绑定调用 ID、副本摘要、工具名及实际文件清单与内容摘要。
  父侧再次读取和校验产物，不仅相信 worker 的成功文本。
- 只读工具、重命名预览不得产生文件变更。普通 write/edit 只能改请求文件；
  符号跨文件重命名必须有完整授权范围。异常删除、额外文件和链接拒绝接受。
- 所有目标先检查权限和基线，然后逐文件 CAS 写入并记录持久日志。
  中途撤权或失败不会自动重做、自动回滚或把部分写入报告成整体成功。
- 会话 anchors 绑定文件内容摘要。副本变化后旧 anchors 不再沿用；
  只有结果被接受并取得物理终止证明后，才能更新下一次调用的 anchors。
- 目录选择与计算共用一个执行租约。第一方驱动先运行固定 Git/rg 只读查询，
  再请求监督器导出文件，最后进入仅有私人副本的计算沙箱。
  第三方进程不接收监督器 RPC 凭据，不增加另一套 manager 或任务队列。
- `ready` 消息只表示计算产物就绪。结果核验、受控提交、确认回执、物理退出、
  会话结果发布依次进行；大结果经过摘要校验后分块返回。
- 同一会话和权限配置使用固定私人副本/缓存路径，并保留源文件 mtime。
  下次调用必须等上次终止确认后才可清理旧副本；缓存保留，越界链接不会被跟随。
  权限或实例契约变化后使用新的缓存命名空间。
- ReadSeek 与 MCP 共用 `supervised-stdio` 传输；它们分别声明自己的绑定和协议。
  这不改变 Codex 使用官方 CLI 与原生工具的路线。

## 文件选择语义

原 ReadSeek 的目录搜索优先使用 Git：默认包含 tracked 和未忽略的 untracked，
也可以显式选择 cached、others、ignored。新适配保留这些类别和 NUL 分隔的文件清单。
worker 的 Git 适配入口只回答已导出的固定 `ls-files` 查询，不能执行其他 Git 命令。

Git 可能选中 `target/`、`node_modules/` 中被跟踪的文件；不能把它们交给普通目录遍历
而静默遗漏。没有 Git 时，目录遍历按上游规则跳过 `.git`、`.readseek`、`target`、
`node_modules`。无法表示的文件名（控制字符、反斜线或无效 UTF-8）明确失败，
与 agentcfg 现有路径边界一致。

子目录会话的 workspace rename 保留原始 cwd 范围，不扩大到整个项目。
只读搜索遇到被权限排除的文件时标明范围不完整；跨文件写入不接受不完整范围。
grep 先使用原项目的忽略规则选文件，再在副本内使用显式 rg 绑定，
不扫描全局 rg、读取环境配置或触发 SDK 的工具下载。

私人副本路径映射回业务路径前，先核验副本路径前缀没有出现在原始正文或用户输入中，
避免误改用户提供的源代码文字。该检查必须在原生计算开始前完成。

## 显式绑定

在机器覆盖的对应 `agent_options` 下设置：

```toml
[overrides.profiles.pi-default.agent_options.readseek]
node_tool_ref = "readseek-node"
git_tool_ref = "readseek-git"
rg_tool_ref = "readseek-rg"
max_seconds = 300

[overrides.profiles.pi-default.agent_options.readseek.settings]
syntaxValidation = "warn"
imageMode = "auto"
timeoutMs = 300000

[overrides.profiles.pi-default.agent_options.readseek.settings.display]
edit = "expanded"
write = "expanded"
grep = "compact"
```

这些引用必须指向已声明的 `external_tools`，同时取得 `bash` 工具对应
`tool:<引用名>` 的 `execute` 允许规则。Node 必须绑定锁定版本；Git/rg 必须是
无额外参数、非交互、只读且只绑定该项目的工具声明。文件读写另外接受 FilePolicy 检查，
命令允许规则不能代替文件权限或工作区写租约。

只读文件上限沿用普通 read 的 16 MiB，写入上限沿用普通文件工具的 1 MiB。
单次副本最多 10,000 个文件和 128 MiB，结果最多 32 MiB；超过限制明确失败。
没有选定 Node、Git 或 rg 时显示缺绑定，不自动借用全局工具。

## 尚待完成

1. macOS x86_64 没有上游 0.9.16 预构建包；显式 sync 现在走本机源码构建。
   前提为 Git、Zig **0.16.0**、make、Python 3、patch 和 Xcode SDK。构建使用
   `agents/pi/build/readseek-source.json` 中固定的 ReadSeek、SQLite、zig-clap、zigimg 和 PDFium 提交，
   核对构建脚本与上游 PDFium 依赖锁的摘要，在独立临时 HOME 中下载和编译；Zig 依赖使用源码中的内容哈希。
   保存 Mach-O x86_64 产物摘要、SDK 版本与静态依赖许可证，失败不激活运行包。
   此入口已通过替身测试，**尚未在 macOS Intel 实机执行**；构建成功也不会自动标原生验收通过。
   Linux 两种架构与 macOS arm64 继续使用固定平台包。
2. PDF/image/vision、原生缓存连续性和完整九工具的真实宿主验收。
   两个固定视觉文件共 1,552,463,168 字节，已实际下载并通过大小、SHA-256 和 GGUF 格式核验，
   但没有执行推理。数据完整性不等于图像理解或 PDF 处理已通过。
3. 四配方依赖锁已写入仓库；最终候选安装和冷重建验证仍待完成。中间候选四配方已完成包含原生文件与视觉资产的安装/密封检查，
   后续源码变化不能继承该候选的安装或原生通过身份。

其他三个平台依照用户决定继续保留未验证；当前 Linux x86_64 也尚未执行 ReadSeek 原生验收。

## 验证记录

- Python 定向回归 51 passed：文件副本、原子文件边界、多文件日志、产物接受、
  anchors、Git 类别与运行包构建。
- Node 隔离回归 8 passed：工具包装、worker 注册与取消、计算产物、固定 Git 查询。
- 固定 Node 24.14.0 下，原插件通过 Jiti 2.7.0 加载，九工具契约与保存的 JSON 一致。
  仅登记工具；没有调用工具、启动宿主、联网或执行原生程序。
- 六个 ReadSeek runtime 模块按安装器规则转换为 `.mjs` 后语法检查通过。

以上为初始边界批次。后续监督控制器、视觉资产与缓存批次已完成完整默认回归：
1406 passed + 7 subtests，Node 216 passed。之后 bootstrap 可用性查询补充由 20 项 Node 定向回归覆盖。
详见 [视觉与缓存验证记录](acceptance/pi-readseek-vision-mock.md)。

完整默认回归和原生/实网结果应以各自报告为准，本页不继承之前候选的通过身份。
