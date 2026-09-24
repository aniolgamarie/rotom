# 使用流程

1. 在 agentcfg 本机配置中选择配方、backend、模型角色、项目根、网络路线和权限。
2. validate/plan 后部署；显式 lock/sync 安装选中切片。源导入不代表已安装或认证。
3. Pi 中使用 model_delegate；需要用户高级操作时使用本目录 scripts/run-model.sh。
   独立 CLI 使用 --instance 指定已有部署，不能与交互 Pi 抢实例锁。
4. 通过 status/poll/wait 查看同一 run。unknown 时保留保护；不要用新 run 覆盖未知写入。
5. 完成后核对当前凭证、artifact 和覆盖范围。使用 result 的 next_offset 阅读完整长结果。
6. cancel 不回滚候选；resume 必须证明旧执行停止。实际停止恢复走 agentcfg recover pi 的明确停止计划。

Codex implement 必须 explicit-write、--allow-workspace-write、--worktree-root 三者齐备；
目标为与已配置项目同一 Git 来源的独立 linked worktree。模型工具和 Pi backend 不能写。
原始 checkout、账号和旧环境不会因这套迁移流程而被清除。

官方 Codex CLI 在启动前检查系统／受管配置和实例账号类别。系统目录非空、组织或未知账号等无法核验的环境会明确拒绝，保留兼容性缺口；不要删除管理员配置来绕过检查。运行期间须保持机器管理配置和账号类型稳定。准入通过与真实模型验收分开，未执行 native/live 时不能宣称该环境已通过。
