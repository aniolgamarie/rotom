# 验收记录

实现与证据分开记录。规划产物完整、测试文件存在、或第三方进程退出 0，都不单独代表对应功能已通过。

审查后的改进对应 `harden-agent-config-after-review`，后续外部验收计划见 [改进计划](improvement-plan.md)。下方原生宿主/安装表记录此前执行结果；本轮修复没有重新启动第三方宿主或执行账号调用。

## 已执行环境

- 日期：2026-09-13。
- Linux x86_64，Python 3.11.11，uv 0.12.13。
- DSH 工具链：官方 Node 24.14.0（校验归档 SHA256）、npm 11.19.1（校验发布 integrity）。完整锁包含 755 条 package 记录。
- 默认测试在临时 HOME/DSH_HOME/XDG 下，使用网络/进程阻断和假进程。文件/权限测试在真实文件系统环境复核，避免容器的 UID 65534 根目录映射制造假失败。

## 原生与依赖证据

| 检查 | Linux 结果 | 边界 |
|---|---|---|
| npm 完整锁解析 | 通过 | 所有 host 组件固定为 0.1.5-rc.1；TUI/Cursor vendor 有补丁和 integrity |
| npm ci frozen 安装 | 通过 | 含最终 Node/npm；不使用 force/legacy-peer-deps |
| npm ls --all --omit=dev | 通过，无 problems | 实际依赖树比对 |
| CLI sync/apply/doctor | 通过 | 新临时实例，复用已准备缓存并启用 offline |
| 原生配置 dump | 通过，有实际配置输出 | 排除了 Node 24.1 空输出但退出 0 的错误工具链 |
| API/MCP 原生 schema | 通过 | 虚构服务数据，未请求模型或 MCP 服务 |
| 真实 DSH/TUI 启动 | 通过 | 创建原生 Agent，standard preset 可用 |
| Codex/Cursor 认证入口 | 通过 | 原生 auth 与 cursor-login 注册；未登录 |
| Cursor loopback proxy | 通过 | 隔离临时端口 /health 返回预期服务身份 |
| 完整技能与 OpenSpec 发现 | 通过 | DSH 原生 Agent 作用域发现 2 个框架技能及 6 个 OpenSpec 技能 |
| OpenSpec 指定项目初始化 | 通过 | 10 个声明产物；重复执行 changed=0；Git 根要求明确 |
| Codex/Cursor 实际模型调用 | **未执行** | 需要用户账号与明确 live 授权 |

可复现的无账号检查（需已安装匹配当前锁的 runtime，且 PATH 中 Node 版本正确）：

```sh
.venv/bin/python scripts/smoke-dsh.py --allow-host --runtime /path/to/locked/runtime --with-openspec
```

该脚本创建并清理自己的临时 HOME/Git 项目，只关闭本次测试宿主；屏蔽模型/登录所用 fetch，并验证本地 proxy health。它不读取现有用户 OAuth。原生模型输出随机性不在框架复现承诺内。

## 平台与待验证项目

| 项目 | Linux 本机 | GitHub Linux CI | macOS CI/本机 |
|---|---|---|---|
| 管理器完整离线测试 | 814 passed，7 subtests passed（2026-09-15） | 工作流已配置，未触发远端执行 | 工作流已配置，未执行 |
| 无账号原生 smoke | 已执行通过 | 独立显式步骤，不默认运行 | 未执行 |
| 真实订阅调用 | 未执行 | 不自动运行 | 未执行 |

维护 skill 已通过结构检查，并完成一次独立 Agent 的“私有模型、保留既有配置、仅生成”行为验证：在临时仓库副本新增网关与逻辑模型，保留 Codex/Cursor 选择、原始注释与秘密原文；validate/render/plan 均返回 0，11 项产物、0 冲突、0 漂移。评估器另行检查原文和秘密保留、缓存不含 canary、实例及部署状态未创建。

该行为测试使用真实 Python 管理器，未启动 DSH 或模型服务。首次临时虚拟环境缺少 pyvenv.cfg 暴露入口循环，已补被动失败回归；沙箱 UID 映射问题通过相同临时环境下的受审查执行解决，没有关闭路径保护。该结果只证明改进计划中的 A 场景，B–E 场景仍待独立行为验收。

## 限制

- 首版仅 DSH；其他工具需真实适配器、依赖后端和原生验收。
- capture allowlist 包括 terminalImages、支持主题和当前已声明模型的原生选择；未声明动态模型或任意自定义主题明确报不支持，不全量导出原生配置。
- 项目集成要求在最近 Git 工作树根初始化；非 Git 项目需从初始化目录启动。
- 私人写入目录的安全祖先要求可能拒绝共享可写路径，不能关闭保护来掩盖失败。
- Native prefs、恢复会话 preset、SDK 的未知容量默认值仍有各自语义，详见 DSH 文档。
- 模型账号及真实服务调用未验证。后续步骤见 [live 验收](live-acceptance.md)。

## 首版完整离线测试（历史）

执行 `.venv/bin/python -m pytest -q -p no:cacheprovider`：**756 passed，7 subtests passed，0 failed，280.20 秒**。这包含源路径修复、OAuth 无静态地址回归、配置/技能/CLI、依赖失败、字段部署、上一版备份、故障恢复、活动锁、启动密钥和项目隔离测试。之后仅更新文档/验收状态，无生产代码变更。

`uv lock --check --offline` 与 OpenSpec strict 校验通过。管理器从无额外构建后端的仓库入口运行；uv.lock 中的依赖保持锁定。需求编号到证据入口见 [验收矩阵](acceptance-matrix.md)。

## 审查修复后的完整离线测试

执行 `.venv/bin/python -m pytest -q -p no:cacheprovider`：**788 passed，7 subtests passed，0 failed，238.25 秒**。包含 R1–R6、安全定位、主题/已声明模型 capture、非 npm 后端完整命令路径和损坏虚拟环境入口回归。此前第一轮全量的 5 个失败已修正，最终结果以本段为准。

原 Spec 与 `harden-agent-config-after-review` 的 OpenSpec strict 校验通过；`UV_CACHE_DIR=/tmp/rotom-uv-cache uv lock --check --offline`、维护 skill quick_validate 及文档链接检查通过。npm package-lock.json 与 uv.lock 的字节未改变，依赖版本与运行包锁身份未改变；新增锁策略和 manifest recipe 摘要。

本轮没有重新执行真实 npm 安装或 DSH 原生 smoke。安装修复由假安装器、真实临时文件与失败注入验证；已有 Linux 原生证据属于同一依赖版本此前的执行。macOS、远端 CI 和真实订阅调用仍按改进计划待验证。

## 工具链与适配器复审（2026-09-15）

最终版本执行 `.venv/bin/python -m pytest -q -p no:cacheprovider`：**814 passed，7 subtests passed，0 failed，227.27 秒**。fresh reviewer 独立复审未发现剩余可操作缺陷，并独立完成 **31 passed，35 deselected，31.17 秒** 的定向回归。compileall、git diff --check、修改文档的本地链接检查通过。

sync 接受 Node 24.2.0 起的 24.x 和 npm 11.x，run 使用相同 Node 范围；lock 仍要求精确 24.14.0 / 11.19.1。Node 24.1.0 缺少入口需要的功能，继续拒绝。元数据缓存经复审发现可能漏检同长度修改，已撤回，status 保持每次正文核验。完整发现、回归及锁摘要见 [本次复审记录](review-2026-09-15.md)。

本次未启动第三方宿主或进行真实安装/账号调用；其他通过版本检查的工具链不据此视为完成原生验收。
