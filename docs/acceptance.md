# 验收记录

实现与证据分开记录。规划产物完整、测试文件存在、或第三方进程退出 0，都不单独代表对应功能已通过。

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
| 管理器完整离线测试 | 756 passed，7 subtests passed | 工作流已配置，未触发远端执行 | 工作流已配置，未执行 |
| 无账号原生 smoke | 已执行通过 | 独立显式步骤，不默认运行 | 未执行 |
| 真实订阅调用 | 未执行 | 不自动运行 | 未执行 |

维护 skill 已通过结构检查，合法配置与生成/部署边界由隔离流程测试覆盖；尚未进行独立 Agent 自动执行该 skill 的行为评估，不能将普通测试写成 Agent 行为已验收。

## 限制

- 首版仅 DSH；其他工具需真实适配器、依赖后端和原生验收。
- 当前 capture allowlist 只包括 terminalImages，不全量导出原生配置。
- 项目集成要求在最近 Git 工作树根初始化；非 Git 项目需从初始化目录启动。
- 私人写入目录的安全祖先要求可能拒绝共享可写路径，不能关闭保护来掩盖失败。
- Native prefs、恢复会话 preset、SDK 的未知容量默认值仍有各自语义，详见 DSH 文档。
- 模型账号及真实服务调用未验证。后续步骤见 [live 验收](live-acceptance.md)。

## 完整离线测试

执行 `.venv/bin/python -m pytest -q -p no:cacheprovider`：**756 passed，7 subtests passed，0 failed，280.20 秒**。这包含源路径修复、OAuth 无静态地址回归、配置/技能/CLI、依赖失败、字段部署、上一版备份、故障恢复、活动锁、启动密钥和项目隔离测试。之后仅更新文档/验收状态，无生产代码变更。

`uv lock --check --offline` 与 OpenSpec strict 校验通过。管理器从无额外构建后端的仓库入口运行；uv.lock 中的依赖保持锁定。需求编号到证据入口见 [验收矩阵](acceptance-matrix.md)。
