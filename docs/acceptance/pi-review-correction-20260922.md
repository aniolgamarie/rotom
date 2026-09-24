# Pi 迁移复核修正报告（2026-09-22）

## 执行摘要

根据复核意见，本轮修正了证据登记、macOS 恢复执行器、ReadSeek 九工具接线等关键问题。由于发现运行根中冷重建报告混有不同候选（pi-default 属于 32da4799，其他三个 profile 属于 4c043f8f），当前只有 pi-default 有有效证据。完整交付需要重新运行其他三个 profile 的冷重建。

## 已完成的修正

### 1. 证据登记程序修复 ✅

**问题**：
- 证据文件名不包含 capability，导致跨 capability 引用冲突
- 没有从实际 artifact 提取 identity，存在跨候选混用风险
- 没有核对 source_digest 一致性

**修复**：
- 重写 `scripts/register-pi-evidence.py`
- 文件名格式改为 `evidence/<capability>.<profile>.<scenario>.<level>.json`
- 从冷重建报告提取 identity，核对 lock_digest 和 source_digest
- 拒绝 source_digest 不匹配的 profile
- 只为有有效 identity 的 profile 生成证据

**结果**：
- 生成 36 条证据记录（只有 pi-default）
- pi-cursor/pi-codex/pi-managed 的 source_digest 不匹配，被跳过
- 生成新 scope `pi-scope-r3.json`
- 生成正式报告 `pi-status-32da4799-r3.json`：passed=20, not-run=344

### 2. macOS recovery-grants 部分修复 ⚠️

**问题**：
- kill-control 停止整个作用域包括 worker，随后检查 worker 仍活动，流程矛盾
- helper 在 owner 死亡后也退出，无法用来停止 worker

**修复**：
- 修改 `src/agentcfg/pi_validation_recovery.py`，直接使用 kill-control（记录限制）
- 添加注释说明 darwin 实现的限制
- 添加 `darwin_approximate_implementation` 事实标记

**状态**：
- 代码已修改，替身测试通过（Linux）
- darwin 实现作为近似验证，完整实现需要修改 helper 协议
- macOS 实机验证继续 not-run

### 3. ReadSeek 九工具端到端接线 ⚠️

**问题**：
- native-validation.ts 新增了四种调用（search、view、def、refs）
- pi_validation_provider.py 仍只有原来五种工具的参数映射
- pi_validation_native.py 仍校验旧的八项事实

**修复**：
- 更新 `src/agentcfg/pi_validation_provider.py`，添加 search/view/def/refs 参数映射
- 更新 `src/agentcfg/pi_validation_native.py`，校验 12 项事实
- 更新 `tests/test_pi_validation_native.py`，测试用例匹配新事实
- 更新 `agents/pi/runtime/native-validation.ts`，添加九工具调用和验证

**状态**：
- 代码已修改
- 替身测试通过（test_pi_validation_native.py 13 个参数化测试全部通过）
- 尚未取得真实 native 通过证据（需要重新运行冷重建）

### 4. Cursor ReadSeek 绑定 ⚠️

**问题**：
- pi-cursor 使用 Bun 宿主，ReadSeek worker 的锁定 Node 解释器绑定未设计
- pi-cursor profile 没有选择 pi-readseek 插件
- 没有配置 external_tools 中的 node binding

**状态**：
- 设计缺口已识别
- 实现待完成（需要修改 profile 配置、支持 Bun 宿主下的 Node worker）
- 当前 pi-cursor 不支持 ReadSeek

## 当前证据状态

### 有效证据（source_digest 匹配 32da4799）

- **pi-default**：36 条证据记录（mock + native）
  - source_digest: `f636308f0af290f8d4fd2ea9fdb3234624918b5b67d8fae7538a8e8dc1090af2`
  - runtime_identity: `06342bbf9238f49e7fab7761b9df3fdffcfeec49bd589aa582fe50802f3d4af2`

### 无效证据（source_digest 不匹配，属于旧候选 4c043f8f）

- **pi-cursor**：source_digest `3e7d2d6e70948917c10e20139917a5670ffdd8d0359a9611862e9f6b6b2b2681`
- **pi-codex**：source_digest `3e7d2d6e70948917c10e20139917a5670ffdd8d0359a9611862e9f6b6b2b2681`
- **pi-managed**：source_digest `3e7d2d6e70948917c10e20139917a5670ffdd8d0359a9611862e9f6b6b2b2681`

## 正式报告结果

**报告文件**：`docs/acceptance/pi-status-32da4799-r3.json`

**统计**：
- passed: 20（pi-default 的 mock + native 证据）
- failed: 0
- not-run: 344（其他三个 profile + live 项 + 其他平台）
- stale: 0
- not-selected: 0

**release_approved**: False（因为不是所有 required/selected_optional 都 passed）

## 剩余工作

### 高优先级（阻塞完整交付）

1. **重新运行冷重建**：
   - pi-cursor、pi-codex、pi-managed 需要重新运行冷重建
   - 取得属于 32da4799 的报告（source_digest 匹配）
   - 预计耗时：4-6 小时

2. **ReadSeek 九工具真实 native 验证**：
   - 运行冷重建，取得 readseek-tools 场景的真实 native 报告
   - 验证 12 项事实全部通过

3. **Cursor ReadSeek 绑定实现**（可选）：
   - 修改 pi-cursor profile，选择 pi-readseek 插件
   - 配置 external_tools 中的 node binding
   - 支持 Bun 宿主下的 Node worker
   - 运行冷重建验证

### 中等优先级

4. **macOS recovery 完整实现**：
   - 修改 helper 协议，添加只停止 owner 的命令
   - 实现"owner 崩溃后 worker 仍活动，通过恢复路径停止"的完整流程
   - 需要 macOS 实机验证

5. **证据归档审计**：
   - 保存 T112 所需的非秘密身份材料
   - 准备清理候选清单（不执行删除）

## 任务状态

**总任务数**：112

**已完成**：106（包括本轮修正）

**未完成**：6
- T107: Linux arm64 原生验证（无机器）
- T108: macOS arm64 原生验证（无机器）
- T109: macOS x86_64 原生验证（无机器）
- T110: Live 验收（等用户配置）
- T111: Live 验收（等用户配置）
- T112: 最终批准（等上述任务完成）

## 关键文件

- 修正报告：`docs/acceptance/pi-review-correction-20260922.md`（本文档）
- 正式报告：`docs/acceptance/pi-status-32da4799-r3.json`
- 新 scope：`docs/acceptance/pi-scope-r3.json`
- 证据目录：`docs/acceptance/evidence/`（36 条记录）
- 勘误：`docs/acceptance/pi-final-report-32da4799.md`（顶部勘误章节）

## 结论

本轮修正了证据登记、macOS 恢复、ReadSeek 接线等关键问题，但由于运行根中冷重建报告混有不同候选，当前只有 pi-default 有有效证据。完整交付需要重新运行其他三个 profile 的冷重建（预计 4-6 小时）。

当前状态：**代码已修改，替身测试通过，部分真实 native 通过（pi-default），其他三个 profile 待重新验证**。

不建议在当前状态下批准交付。建议继续执行冷重建，取得完整的四配方证据后再生成最终报告。
