# 按工具维护流程：验收范围与证据

日期：2026-10-26。开发基线为 main `45953f09ce14908282b4af4c08101227e151ca3f`；
候选分支为 `feat/tool-maintenance-workflows-20261026`。候选实现和分组回归已收口，仍待人工整合批准，
本记录不表示 main 已具有候选能力。私人任务记录保存逐文件摘要、原始 argv、退出码和原始日志。

## 行为与兼容性

三工具沿用各自运行和部署保护，通过保存恢复清单、精确停止、独立批准普通 setup、
逐项当前终端恢复形成完整的显式维护流程。没有跨阶段写许可，没有自动继续输入。
以下边界已有实现和针对性回归，整库结果见下方单独状态：

- OMP host 更新复用 `owner_pending` 的 Domain/owner 双向摘要；共享运行包引用仍约束更新。
- Pi/OMP 控制端点置于既有 inbox 的 sidecar，保持旧 RunRecord reader 和 OMP 摘要兼容。
- 普通 setup 保留现有物理锁、运行 owner 和共享资源检查；新并发实例不会被自动加入停止集合。
- `lock` / `sync` 仅显式选择命名代理；不继承普通 run 的代理默认；窄签名后端保持兼容。
- 目标完整运行包没有恢复准入时，在维护停止前拒绝；更新批准前再次核验。独立停止和普通 setup 仍可用。
- 恢复绑定本次批准的部署摘要，在运行共享锁内重核；配置发生变化不会启动错误版本。
- cancel 先保存禁止后续阶段的事实；原停止未确定时保留 fence，返回 4，不重投信号。
- 所有会话头严格 UTF-8 解码。OMP 固定格式的 256 字节标题槽可跳过；标题不作为会话身份，正文不读取。
- help、交互选择、非 TTY 缺参、重复选择、旧停止批次和旧 OMP 查询均分别回归。

主目录已有四个 Pi 锁文件的未提交改动，完整 identity 为
`a68d9dcf3346c0c6ab9bff231f85510dea2d9d25794664cd835cd476c3460587`，
与本候选验收的完整组合不同。本轮未修改或吸收这些文件，也未给新组合补造恢复准入。
当前适配器的只读校验已接受该锁格式；独立普通启动/部署入口保留，但没有据此宣称真实日常部署已验收。若保留该锁用于维护，应先完成其单独验收。不能把本候选的测试结果
当作对主目录未提交组合的通过证明。

## 未修改的官方运行包

| 对象 | 本轮核验 |
| --- | --- |
| Pi 1.3.0 | 官方 tgz 的 SHA-512 SRI 与锁一致；安装目录中归档内 1276 个文件逐字节一致。 |
| OMP 18.12.6 | 固定提交 `45c35e40c46166dc726ccc52f5d27f40f2449f99`；使用官方 Linux x64 二进制，SHA-256 `85d9daf3a05fc76e8cd425ae1904eb576af8d21cc85fcf4690742626e07ccfa4` 与当前 asset 锁一致。 |
| Pi 自有控制来源 | MJS 扩展、Python guard/helper 三个文件均与 `locks/pi/session-control.json` 相符；控制来源 identity 为 `100331dd76bf2740304f7177ca1452660317484f674bb374a48fefae802f5817`。 |
| DSH | 沿用 main 的固定锁原生验收；本轮未重跑 DSH 原生测试。 |

OMP 二进制来自已准备的官方缓存；二进制匹配不表示缓存目录名代表当前完整配置 identity。
Pi/OMP 恢复准入仍绑定[维护指南](../../docs/tool-maintenance-workflows.md)列出的完整锁组合。
没有修改 vendor、缓存宿主源码、官方二进制或导入宿主私有接口。Pi 原生运行使用 Node v24.14.0，满足适配器的 Node v22.19.0 最低版本要求。

## 显式授权的原生验证

Linux、原用户 UID、隔离 HOME/XDG、合成会话；bubblewrap 隔离网络，未访问真实账号或会话。
所有模型标识和密钥值均为测试配置；没有发送模型请求。公开报告使用路径占位值；原始 argv
保存在私人证据内。下表的 RPC 请求是官方控制接口请求，不是模型提示词或终端继续输入。

| 验证 | 观察和退出码 |
| --- | --- |
| Pi 官方 RPC 精确 `--session FILE` | `get_state` 返回请求 ID；正常退出 0。缺失目标可创建新的内存会话 ID，仍退出 0，不能将原生成功当作精确恢复。 |
| Pi 生产公开控制扩展 | 实际初次 claim 和辅助会话观察一致；第二个登记运行争用同 ID 被拒绝；官方 `switch_session` 切换到精确新 ID 后新 helper 观察一致；原 pidfd SIGTERM 后 143。 |
| OMP 官方 RPC 精确 `--resume FILE` | 精确目标返回原 ID、退出 0；缺失目标拒绝、退出 1。 |
| OMP 原生 writer | 两进程可只读打开同 ID；第二进程首次写入通过原生逻辑改用新的 sibling ID，第一进程 ID 不变。原 writer 退出后可恢复原 ID 并写入；三个进程原 pidfd SIGTERM 后均 143。 |
| Pi 官方 TUI / PTY | 只读公开 `session_start` 观察到精确 ID、原 cwd；原生进入 raw mode；输入 0 字节；原 pidfd SIGTERM 后退出 0，终端属性恢复。 |
| OMP 官方 TUI / PTY | 同上；原 pidfd SIGTERM 后退出 143，终端属性恢复。 |

TUI 检查采用额外的自有只读公开观察扩展。Pi 生产 guard 在独立 RPC 检查中验证；
不能把这些分项结果说成一次使用真实官方宿主贯穿全部 Rotom CLI 的停止→setup→恢复测试。
全流程 CLI 的持久化、部署、批准与故障顺序由隔离测试验证，原生协议由上述分项验证。

关键原生 argv 模板（`FILE`、`SESSION_DIR`、`OBSERVER` 均为隔离环境路径）：

```text
node PI/dist/bundle/cli.js --mode rpc --session-dir SESSION_DIR --no-extensions --no-skills --no-prompt-templates --no-themes --no-mcp --no-approve --session FILE
omp --mode rpc --no-extensions --no-skills --provider openai --model gpt-4o --resume FILE
node PI/dist/bundle/cli.js --session-dir SESSION_DIR --no-extensions --no-skills --no-prompt-templates --no-themes --no-mcp --no-approve --session FILE --provider openai --model gpt-4o -e OBSERVER
omp --no-extensions --no-skills --resume FILE --provider openai --model gpt-4o -e OBSERVER
```

Pi guard 检查由生产 `prepare` 在第一条 argv 上追加受锁校验的公开扩展，并通过最小环境传递
控制上下文和继承租约 FD。helper 使用 Python `-I`，不继承 PYTHONPATH 或认证环境。

## 隔离回归与失败历史

默认 pytest 使用临时 HOME/XDG、阻断网络与假宿主；不能作为真实宿主证据。
各组有重叠，不能相加称为全库测试数。

| 范围 | 当前结果 |
| --- | --- |
| header 最终组，含 UTF-16/32 负例 | 78 passed；退出 0。 |
| Node 公开控制扩展最终组 | 43 passed；退出 0；全部子进程均为替身。 |
| Pi 观察 / guard / runtime 阶段组 | 250 passed；退出 0。后续部署绑定变更另跑受影响组。 |
| workflow / resume / runtime / CLI 最终组 | 353 passed / 4 skipped；退出 0；生产与测试摘要稳定。四项为 Pi 专属场景的非 Pi 参数跳过。 |
| 旧 CLI / footer 契约修复 | 99 passed；退出 0。 |
| 命令历史隔离 | 116 passed；退出 0；相对哨兵不依赖临时根路径格式。 |
| 整库分组阶段 | 首段 4629 passed / 8 skipped / 8 failed 后主动中断；四组依次为 2239 passed / 1 failed、2235 passed / 2 skipped / 3 failed、2239 passed、2233 passed / 2 skipped / 4 failed。原始失败记录保留。 |
| 后续完整文件复验 | 预览/部署 55 passed；OMP 实例 15 passed；恢复工厂 29 passed；所有分组阶段失败均已通过相应完整文件复验。 |

初轮隔离失败、错用沙箱假 Node 所得单文件结果、原生环境准备失败、Pi helper 的 stdlib
名称遮蔽错误和 OMP writer 冲突行为的错误预期均保留在私人证据中；后两项已分别修复并重跑。
审查发现的部署 TOCTOU、取消与停止收尾耦合、UTF-16/32 自动探测，以及 help epilog 被覆盖
均已修复，最终受影响组合已通过。测试替身自身的失败与生产缺陷分开记录。分组期间出现的旧工具准入预期、额外控制扩展与 UI 链排序、fake child hook，以及临时目录格式依赖均已更新并完整复验；没有修改生产代码来迁就旧断言。

最终稳定收集共 **13,573** 个唯一测试节点。按首段、四个分组及受影响完整文件复验逐项对账，结果为 **13,561 passed / 12 skipped / 0 未解决失败 / 0 未覆盖**。重叠测试只计一次；5 个已被替换的旧工厂测试 ID 记录为替换，不冒称原 ID 重跑通过。首段另有 7 个通过的 subtest，不计入上述节点总数。这是分组及复验汇总，不是一次未中断的全绿运行。

12 个跳过项包括 7 个已退休 OMP 宿主补丁测试、1 个未提供可选锁定 Bun 材料的官方 SDK 测试，以及 4 个 Pi 专属测试在 DSH/OMP 参数下的跳过；均未计作通过。

严格加载回执、原 Herdr pane 恢复、自动继续及其它平台均未由本轮开放。
这些条件能力不是本轮分阶段维护流程的隐藏前置。main 整合保留为独立人工批准步骤。
