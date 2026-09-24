# OMP 提交前审查

日期：2026-09-24。授权：用户要求审查通过后提交本次 OMP 变更。管理器基线为 `e208e2df50c7f21095d2ec7eb081dfc4df4f7156`；固定 OMP v18.3.0 / `62bc57be1b03ef0802a33cf7f5f530e534527531`。

## 实际发现与修复

1. 通用 schema 的组合分支误将 `prefixItems` 视为可省略显式类型，也允许带类型数组的节点绕过严格检查。限定为不含 `type` 的 allOf/anyOf/oneOf；两条负测先失败，修复后 schema、OMP adapter/foundation 组合 **137 passed in 2.53s**。
2. 原生 `PERSONALITY.md` 会影响系统提示词，但未列入发现门禁。补齐 active/default 两处来源；两条负测证明新增文件在 spawn 前被拒绝。
3. 原生 `PI_CONFIG_DIR` 会改变配置根目录。补齐 caller、machine inherit/values、AdapterPolicy 和最终启动环境保护；四条负测覆盖各入口，另验证普通环境变量仍可用。

后两项负测先得到 **6 failed, 9 passed**，修复后来源/运行基础/发现/profile 组合 **113 passed in 3.46s**。执行者为 executor（实际模型 gpt-5.6-sol / medium），主代理复核差异及环境校验调用路径。scout（实际模型 gpt-5.6-luna / medium）独立检查依赖、inventory、usage：关于缓存根目录权限的疑虑由现有 `Tree(root)` 检查排除；下载重定向建议未作为缺陷采用，固定 GitHub 发布资产依赖 CDN 重定向且内容受固定 SHA 校验。未因此扩大本次范围。

## 锁与证据版本

发现清单从 47 项增加至 49 项，摘要 `20faec67ce8ebadae48e3222dbc207f5a503ab483b09d7432db59ff0089e9afd`。使用已校验的固定源码归档和 SHA256SUMS 重新 resolve_lock，并 read_lock 相等校验；当前正式锁身份为 `2b8971c55f9b8680cd0b61e705d81e5f9f0e725f22705582798066bb88016cc4`。

上游版本、发布资产和自检包未改变；[Linux smoke](linux-smoke.md) 保留当时锁身份与实际观察。本轮没有重跑真实宿主或账号操作，新增门禁由隔离测试验证，不将历史 smoke 写成新锁的实机执行记录。

## 最终验收

Linux x86_64 / glibc 2.32，Python 3.11.11；执行 `.venv/bin/python -m pytest -q --tb=short`，退出 **0**：**2160 passed, 7 subtests passed in 126.29s**，无失败、无跳过。该次全量在所有审查代码修复和正式锁重生成之后运行，覆盖 DSH/Pi/OMP。使用默认测试内临时 HOME/XDG、网络与子进程隔离；执行工具采用正常权限视图，未放宽生产权限检查。

提交暂存区检查通过：113 个文件均匹配显式 OMP 变更清单，46 篇 Markdown 的 228 个相对链接目标均存在于 Git 索引；`git diff --cached --check` 退出 0；高置信度私钥/token 模式扫描无命中。除有意只暂存 OMP 内容的遗留索引外，暂存内容与已验收工作树字节一致。没有剩余阻塞发现。

## 提交边界

README 的原生支持状态已与 Linux x64 证据和独立遗留保持一致。上游 THIRD-PARTY-NOTICES 按锁定原始字节保留；`.gitattributes` 仅对该文件豁免空白检查并禁止文本转换，其他源码和文档继续执行空白检查。

提交使用显式文件清单；原有 `.codex/`、`.pi/`、两篇非本次缺陷文档保持在工作区，遗留索引只暂存本次 OMP 条目。当前 spec 仍为 62/62；[OMP-F01–F05](../../../docs/follow-ups/omp-platform-and-live-validation.md) 均保留环境不足未验证状态，不阻塞本 spec。
