# 2026-09-28 review 修复记录

基线：`a49e0fc`。本轮处理 review 确认的四项缺陷、当前文档与历史验收边界，并接入已有 Task Keeper 隔离 mock。没有改变原生运行包锁，也不把历史验收改写为当前候选通过。

## 已完成

| 项目 | 修复与回归边界 |
| --- | --- |
| termcfg 恢复门禁 | 统一 journal 存在检查，悬空符号链接也视为恢复标记；计划、环境/状态、apply 和 rollback 不再把它当作不存在。测试要求 journal 保持原样且不写 HOME 目标。 |
| TOML 错误定位 | 公共来源显示类别及加载序号，私人来源显示 local；保留行列号，隐藏正文、私人路径和原始异常上下文。覆盖多来源、不同出错行、EOF 与合成秘密。来源序号解释见 [配置参考](local-config.md)。 |
| OMP 日志边界 | 有界尾部读取检查截断位置前一字节，行首保留完整事件，行中舍弃残片。覆盖两个边界，不读取按键。 |
| secrets 文档 | 撤销会生成宽权限备份并截断内容的 grep/sed 操作；改用独立无秘密提案，由用户审阅合并非秘密字段，真实机器文件保持完整。分文件功能仍属 SEC-F01。 |
| 当前架构与历史证据 | 更新 AGENTS、架构入口、Pi 指南及支持矩阵；旧架构笔记标记历史。Pi 候选锁 `9d6a9270…` 的关闭证据不继承为当前锁/源码通过。 |
| 持续集成 | 增加独立 Task Keeper mock job，固定 Node 24.14.0、消费 fixture 完整锁，使用已有临时 HOME 和禁网/禁宿主入口；锁变动检查覆盖所有工具。 |

执行分工：主代理负责方案与最终验收；executor（gpt-5.6-sol / medium）实现代码及定向回归；scout（gpt-5.6-luna / medium）核对 CI 依赖与已有入口。

验证环境：Linux x86_64，仓库 Python 3.11.11，Node 24.14.0。

| 验证 | 实际结果 |
| --- | --- |
| `.venv/bin/python -m pytest -q --tb=short` | **2363 passed，7 subtests passed**，220.77 秒。含新增的 6 个回归测试；没有启动第三方宿主。 |
| `node agents/pi/packages/task-keeper/scripts/test-mock.mjs` | **36 passed，0 failed**，约 1.45 秒。使用已有 fixture 依赖和 bwrap 隔离入口。 |
| executor 定向回归 | termcfg 108 passed；配置解析相关 222 passed；OMP 输入诊断 10 passed；有效 plan-id 注入 journal 的增强回归 2 passed。 |
| 文档与工作流 | 修改文档的相对链接目标检查通过，工作流 YAML 解析通过，`git diff --check` 通过。 |

`setup-node` 使用 [v4.4.0 对应固定提交](https://github.com/actions/setup-node/commit/49933ea5288caeca8642d1e84afbd3f7d6820020)。新增 CI job 的本地测试命令已通过；尚无远端 workflow run 证据。

## 进行中

无。本轮四项具体缺陷的实现、回归及最终工作区验收已完成。

## 失败待决策

本轮四项缺陷没有待决策事项。新发现的 Task Keeper 开发依赖锁与 package.json 不一致，类型检查接入独立记录为 [REVIEW-F02](follow-ups/taskkeeper-typecheck.md)，未把 mock 通过当成类型检查通过。

## 环境不足或未执行

- 默认沙箱将 `/` 属主映射为 UID 65534，私人路径检查会失败；有效 Python 验证在根目录属主正常的环境执行，测试本身仍使用临时 HOME、网络阻断和假进程。
- 默认沙箱拒绝 bwrap 所需命名空间；Node mock 在允许 bwrap 的环境执行，bwrap 内禁网、仓库只读、仅临时目录可写。
- 未运行远端 CI、其他平台、真实宿主、真实账号/服务或当前 Pi native/cold 验收。
- Task Keeper `tsc --noEmit` 未运行，其开发依赖环境待 REVIEW-F02 处理。
