# 当前 Base 安装闭包的官方 SDK 六场探针

2026-10-08（本地），当前 review01：用户明确授权后首轮 sdk01 已完成，六项均 observed，child／wrapper／tool outer 均退出0；无需修复或重跑。本次针对 npm 定向覆盖后实际保存的安装闭包；旧 SDK6 授权及观察保留为历史，不能直接替代这份闭包的执行证据。

授权前准备执行器为 `.cache/pi-two-profiles/run-20261004/modern-base-installed-sdk-six-preparation-review01/executor.py`，21,346B，SHA256 `8ad7b2f5ec599ea35432b3b395d7c8d377db2c74582d36c999972528fd096359`。当时固定 `EXECUTION_AUTHORIZED = False` 在创建运行目录或子进程之前拒绝执行，命令行不能覆盖。原执行计划 `executor-plan.json` 为5,595B，SHA256 **`93d239bf5019e321a33c6ff370747cec9dd91d04f292d0a6d07faeee39c8f789`**，其历史 `execution_authorized=false` 原件保持。授权后只打开自有执行器守卫，新摘要和前像见本文末；同边界必要修复和重跑均须保留独立记录。

root完整审阅执行器的新材料／树检查、实际结果捕获和失败保留；独立 scout（配置 gpt-6-luna/high）稳定静态审查为0 P1／0 P2。34输入 root preparation receipt 为 `5d6d2b4c332b4ddc69d3b3535a16cbfba8fce59b6ffacc7c6dac2b61be9d7925`。一次 stdlib fake 验证5项通过，未执行 SDK、Node、bwrap 或 timeout，不属于原生证据。

## 固定输入与六项断言

本次使用实际独立开发安装的保存树，安装 receipt 为 `3749a2962388ee5236231b47196537b023b1dd871beb8fff1782ec8575f2feb2`。完整树 inventory 为5,318,454B，SHA256 `4456d8b746f35694d272a4980021490c5299cb277bf1d497da24eca930f882f3`，共16,653条目：15,184 regular files、1,460目录、9个受限相对 `.bin` 链接、124,615,286 regular bytes。执行前后逐项核对精确路径集合、类型、模式、owner、nlink、完整文件SHA与记录的链接目标；这是端点检查，不是持续 source hold。

只读候选挂载是 `modern-base-isolated-install-preparation-review01/install01/installed-tree/pi-base-1e4f9e6dc96d1083ed6b201deef2356cea8dcf743839db887f703f7ae386a76f`。官方包仍为 Pi coding-agent1.0.1／pi-ai1.0.2；使用未修改的包根公开 exports，不使用私有接口。原探针 `scripts/pi-probe-official-sdk.mjs` 的14,715B／SHA256 `76ede8ec15e1f06696548fac7cd609587dfe6e9a9accc8b09a8ebc9607874e4c` 与12份 fixture 字节全部保持。

六项断言沿用原探针：

1. extension／skill／prompt精确白名单、诱饵不加载、固定SYSTEM／APPEND。
2. 公开嵌套工具调用及真实父子事件身份。
3. `tool_call`拒绝阻断子工具正文并产生错误结果。
4. 公开abort传播父子signal取消。
5. SDK JSON模式 `hasUI=false`，自有需人工操作的工具明确拒绝。
6. 公开reload后资源白名单保持、观察新的session_start。

## 隔离、资源和命令

外层以空环境 `env={}` 调用固定绝对路径 `/usr/bin/timeout` 和 `/usr/bin/bwrap`。bwrap使用 `--die-with-parent --unshare-all --new-session --cap-drop ALL`；网络被隔离，`/usr`、`/lib`、`/lib64`、候选、探针和fixture只读。只把固定Node单文件挂载到 `/node/bin/node`，不挂载整个nvm或账号目录。仅本次自有0700 work为持久可写挂载，另有namespace私有 `/tmp`。探针只接受闭合环境白名单；HOME／XDG／TMP均为自有目录。Provider／凭据均为内存合成材料；不读取真实账号，不请求模型或外网，不启动Pi TUI、Codex或MCP，不部署、切换默认入口或修改上游。

工具 pins：

| 工具 | bytes | SHA256 |
|---|---:|---|
| `/usr/bin/bwrap` | 75,344 | `6f8fe506c26367ebdd0027247e47e0725d4594cc952565cd23f810725d8082f2` |
| `/usr/bin/timeout` | 46,872 | `4e0102f22f4017f2b7b75d95e180896ffaa7cc82160ed4994e18563fb00a6bc2` |
| 固定Node24.14.0文件 | 122,466,960 | `e237a2839d0cbdc9a9a2adda1a184afc0f5b20306ffbe923af5686550472d8a8` |

授权后首轮命令，cwd为本worktree，绝对执行路径在计划中固定：

```text
/usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8
  /usr/bin/python3.11 -I -S -B
  .cache/pi-two-profiles/run-20261004/modern-base-installed-sdk-six-preparation-review01/executor.py
  --execute-after-new-sdk-authorization --run-name sdk01
```

探针内部30秒截止、每异步操作5秒截止；GNU timeout60秒／kill-after5秒，wrapper执行等待70秒，之后使用原有有界shutdown与2秒管道收尾。预／后检查和结果保存有有限字节／条目／深度上限，未计入70秒，不宣称整体硬截止。stdout／stderr各16MiB，结果1MiB；完整树每次检查上限512MiB／65,536条目／深度128，单文件64MiB。

运行输出、工作目录在成功和失败时均保留，不执行rmtree。原进程控制保持leader WNOWAIT观察、未reap时TERM／KILL、随后reap，再观察外层group。bwrap的新session意味着外层group empty不能证明namespace所有后代退出；该资格保持false，未知状态保留原资源，不生成清理通过记录。

## 验收边界

只保存实际SDK生成的work结果原始字节，exclusive600复制并完整读回；退出0须实际文件六场全部observed、版本／ID／闭合shape准确且与stdout最后JSON相等。root另核对原schema、六断言观测和首末材料记录；失败和未运行场景如实保留。此次不验Full／controller／sourcehold、代理联网行为、账号或真实模型质量，也不签产品或发布资格。严格输入计量未验证前AUTO OFF保持。

执行授权依据是仓库 [AGENTS.md](../../AGENTS.md) 测试边界：“真实 smoke 为独立显式步骤，需用户明确授权”。用户针对本 review01、计划 SHA `93d239bf5019e321a33c6ff370747cec9dd91d04f292d0a6d07faeee39c8f789` 回答“授权执行及同边界必要修复重跑（推荐）”。计划原件保持不变；仅打开自有执行器守卫，授权后的执行器为21,345B／SHA `5f600d249430ea43340b633ba4c01bb10330484e35d524e0bdbddb074ff3b2fb`。四项变更前像 receipt 为 `fcdea03517a94ea2b6ea056c2caf4109c3e22eeb2cf9839175967a06b616de38`，三项授权冻结 receipt 为 `6bb98442b372ed71759a0de6012be717ab4143e987e6558ffb50cbe57905529c`。

## 当前 sdk01 实际观察

UTC `2026-10-07T22:16:18.572074+00:00` 至 `22:16:27.755460+00:00`，一次执行。工具首次 chunk `8ca54f`／session79521，完成 chunk `52de32`／outer exit0。实际 SDK 版本 Pi1.0.1／Pi AI1.0.2；六例全部 observed。嵌套拒绝产生 host_error_event；无UI操作明确 denied；reload 观察两次 session_start、extension_errors0。诱饵、context、真实凭据数均0。保存 stdout1540B 与实际结果文件1540B逐字相同，SHA `057defd5b4d342a60e5044bf4fbf8ce213e80847f81717f686aaad9afa9d1273`；stderr0B。实际 execution-report15,934B／SHA `343d37edcec19c18eb9cc4e3feca27888e8b4b2b561157c89b58bf0ac4f50527`。

安装树16,653条目／124,615,286 regular bytes及全部固定材料前后相等。外层正常leader退出后，按已冻结监督顺序在leader未reap时记录TERM和KILL，最终外层group empty／pipes EOF；不由这两项扩大为namespace全后代终止。所有work和原始结果保留，无修复、重跑或自动清理。

独立 scout 配置gpt-6-luna/high仅有界复核已保存结果，没有重扫安装树或重跑SDK。root核对真实argv与原隔离计划、原结果shape和六断言；10输入验收 receipt `cd3624dcfa90984031df7ed70d694c7e81cf1c3fc549df9977a2fcb3e5495684` 位于 `modern-base-installed-sdk-six-root-accept-review01/`。本次grant完成；SDK6限定通过不替代其它RPC／reviewer／来源／Full验收。正式任务仍7/100、产品gate未通过、严格计量前AUTO OFF。
