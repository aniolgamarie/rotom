# US2 原生身份与来源隔离

> 本文保留软件隔离阶段的原始结果与当时限制；后续已授权的 Linux x64 真实验证见 [Linux smoke](linux-smoke.md)，不能将本文历史“未执行”理解为当前平台状态。

日期：2026-09-24。实现executor：gpt-5.6-sol / medium；固定源码检查scout：gpt-5.6-luna / medium。主代理负责边界决策和集成验收。

新增profiles/discovery/login三文件的首轮导入错误不计行为失败证据；建立接口后的实际首轮 **7 failed, 23 passed**，修复后 **39 passed in 0.63s**。组合受影响回归 **382 passed in 6.22s**，均为临时目录和假进程。

覆盖稳定完整hash/native name、保留名/空白/穿越拒绝、改名的新身份、XDG重定向、第二state归属、root/policy改变需重新apply、默认快捷键只读摘要、capture精确绑定profile、token-aware参数；project roots只允许cwd/祖先，skills包和MCP逐项检查，dotenv/系统提示/扩展等其他来源拒绝，内容在spawn前重新扫描。

源码复核发现并修正opt-in不能以声明根作为祖先检查终点：根以上发现路径仍需检查。active/default备用`.mcp.json`被拒绝。项目stdio MCP必须对应锁内echo脚本与已记录的Python要求，不能仅因路径字符串相等而认作锁定。

plan/doctor报告候选身份、HOME/XDG、默认快捷键来源、source_policy和账号范围。没有启动cwd时明确未检查实际项目内容，不把管理仓库cwd误当将来会话cwd。真实宿主profile/来源发现未执行，隔离规则不提供OS sandbox。

## 后续固定源码审查与门控补齐

bootstrap 的 extensions 路径和 models.yml 新增 provider 曾可越过受管声明；新增先行测试实际 7 项失败并触达假进程，修复后 source_gate **9 passed**，受影响组合 **391 passed in 6.55s**。现校验实际扩展与 provider 映射，并拒绝 active/default 的系统提示、备用 MCP、skills.customDirectories 等发现来源。

固定发现清单统一由代码生成并核对 JSON，47 项 native root patterns 与 config/models/MCP 控制项均纳入；摘要 `ce309dfaa9de84e3383af25946110ec8f14fbe11e32449535ab72f39050f8d82`。清单相关组合 **89 passed in 1.16s**，JSON 随正式配方锁校验，最终全量见[回归](regression.md)。真实宿主仍未执行。

后续新增显式 inspect/mcp 自检后，正式锁更新为 `0387bc982c13d768c77cf1be42b0243ebd0fabb0aa0a7ca9048e903d1d1134eb`；受影响隔离回归 57 项通过，真实命令与边界见[Linux smoke](linux-smoke.md)。

后续提交前审查补齐 PERSONALITY 来源与 PI_CONFIG_DIR 门禁，清单和正式锁再次更新；最新结果见[提交前审查](precommit-review.md)。上述测试计数及摘要保留为各阶段历史证据。
