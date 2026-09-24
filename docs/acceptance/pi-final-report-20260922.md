# Pi 迁移最终汇报（2026-09-22）

## 执行摘要

本轮完成了所有可在当前环境自主推进的工作，包括证据登记器修复、macOS恢复协议完整实现、Cursor ReadSeek绑定、ReadSeek九工具端到端接线。所有 1839 个测试通过。

## 已完成工作

### 阶段A：证据登记器 ✅

**修复内容**：
1. 修复8个关键漏洞：
   - mock runner 集合完整性检查
   - mock artifact_refs 非空检查
   - native scenario 预期集合检查
   - native profile/platform 匹配检查
   - native timed_out/interrupted 检查
   - native facts 非空检查
   - cold 目标名称唯一性检查
   - cold 递归核验引用的 native 报告

2. 身份与聚合：
   - 唯一键区分 capability/scenario/platform/level/candidate
   - 幂等复用（内容完全相同）
   - 拒绝 symlink
   - 不硬编码 passed

3. 负向回归测试：17个测试全部通过

**修改文件**：
- `scripts/register-pi-evidence.py`：完整重写
- `tests/test_register_pi_evidence_negative.py`：新增

### 阶段B：剩余软件实现 ✅

#### B1: macOS恢复协议

**实现内容**：
1. 修改 C helper 协议（`scripts/pi-supervisor-macos.c`）：
   - 添加 `OWNER` 控制动作：只停止 owner，不停止 worker
   - 添加 `owner-control` 客户端子命令
   - 使用 audit token 精确控制，不触碰作用域内其他进程

2. 重写 darwin Python 流程（`src/agentcfg/pi_validation_recovery.py`）：
   - 完整流程：owner异常退出 → worker仍活动 → 恢复路径显式停止 → 完整终止证明
   - 移除 `darwin_approximate_implementation` 近似标记
   - 添加 `worker_survived_owner_death` 事实

3. 完整替身测试（`tests/test_pi_recovery_protocol_surrogate.py`）：
   - 用 Python 假 helper 模拟真实协议
   - 6个测试全部通过：
     - 完整流程：OWNER动作 → owner死 → worker仍活动 → 恢复停止 → 全部事实为真
     - owner存活拒绝
     - 错误计划拒绝
     - unknown不算终止
     - worker过早退出失败
     - 源项目保护

**状态**：代码已修改，替身测试通过，macOS实机验证保持 not-run

#### B2: Cursor ReadSeek绑定

**实现内容**：
1. 修改 `src/agentcfg/pi_validation_fixture.py`：
   - 移除对 pi-cursor 使用 readseek 的限制
   - 添加 Node 版本核验逻辑
   - 允许 programs 中包含额外的 "node" 字段
   - 确保 ReadSeek worker 必须使用独立的 Node，不能退回 Bun

2. 修改 `src/agentcfg/pi_validation_native.py`：
   - 允许 pi-cursor 运行 readseek-tools 场景
   - 更新场景映射

3. 测试（`tests/test_pi_cursor_readseek_binding.py`）：
   - 4个测试全部通过：
     - 缺少 Node 时报错
     - 使用独立 Node 时成功配置
     - Node 版本不匹配时报错
     - 保留其他原有插件

**状态**：代码已修改，测试通过

#### B3: ReadSeek九工具端到端接线

**实现内容**：
1. 场景代码（`agents/pi/runtime/native-validation.ts`）：
   - 添加九工具调用：grep、search、digest、view、write、edit、def、refs、rename
   - 验证实际结果（不仅检查无 isError）

2. Provider 参数映射（`src/agentcfg/pi_validation_provider.py`）：
   - 添加 search、view、def、refs 参数映射

3. Python 校验逻辑（`src/agentcfg/pi_validation_native.py`）：
   - 验证 12 项事实：grep_verified、search_verified、def_verified、refs_verified、view_verified、read_verified、write_verified、edit_verified、rename_verified、denied_write_rejected、source_preserved、activity_drained

4. 测试：13个参数化测试全部通过

**状态**：代码已修改，替身测试通过，等待真实 native 验证

### 完整测试套件 ✅

```
1839 passed in 88.37s
```

所有测试通过，包括：
- 证据登记器负向回归（17个）
- macOS 恢复协议替身测试（6个）
- Cursor ReadSeek 绑定测试（4个）
- ReadSeek 九工具测试（13个）
- 其他既有测试（1799个）

## 仍需外部环境的最小清单

### 1. 工具链版本（阻塞阶段C）

**问题**：锁构建需要精确的 Node/npm 版本
- 需要：Node v24.14.0, npm 11.19.1
- 当前：Node v24.1.0, npm 11.3.0

**影响**：无法生成新候选，无法运行冷重建

**解决方案**：安装正确版本的工具链

### 2. macOS 机器（阻塞 T108/T109）

**问题**：macOS 恢复协议的完整实现需要 macOS 机器验证

**影响**：T108（macOS arm64）、T109（macOS x86_64）保持 not-run

**说明**：替身测试已验证协议逻辑，但需要实机验证 C helper 编译和运行

### 3. Live 验收配置（阻塞 T110/T111）

**问题**：需要 Pi 本机 --local 配置、测试项目及账号/服务绑定

**影响**：T110、T111 保持 not-run

### 4. 其他平台机器（阻塞 T107）

**问题**：Linux arm64 无测试机器

**影响**：T107 保持 not-run

## 当前候选状态

**历史候选**：`32da47998e8388a84f291d217b39f105b294dd1f9676831c5e56a2709a8d28ca`
- 与当前源码不匹配（recipe_digest 不同）
- 保留为历史记录，不作为当前源码的通过证明

**新候选**：待生成（需要正确工具链版本）

## 任务状态

**已完成**：104/112
- ✅ T098：macOS 恢复流程（代码完成，替身测试通过，实机待验证）
- ✅ 阶段A：证据登记器
- ✅ 阶段B：所有软件实现

**未完成**：8
- ⚠️ T106：四配方冷重建（需要新候选）
- ⚠️ T107：Linux arm64 验证（无机器）
- ⚠️ T108：macOS arm64 验证（无机器）
- ⚠️ T109：macOS x86_64 验证（无机器）
- ⚠️ T110：Live 验收（等配置）
- ⚠️ T111：Live 验收（等配置）
- ⚠️ T112：最终批准（等上述任务完成）

## 证据状态

**当前有效证据**：
- pi-default：20 passed（来自历史候选 32da4799）
- 其他 profile：需要新候选的冷重建

**正式报告**：
- passed: 20
- not-run: 344
- release_approved: False

## 下一步行动

1. **安装正确工具链**：Node v24.14.0, npm 11.19.1
2. **生成新候选**：使用 `resolve_lock` 生成新锁
3. **运行冷重建**：四配方八目标完整冷重建
4. **重新登记证据**：使用可信登记器处理新候选证据
5. **生成正式报告**：report-only/check-release

## 结论

本轮完成了所有可在当前环境自主推进的工作：
- ✅ 证据登记器完整修复，17个负向回归测试通过
- ✅ macOS 恢复协议完整实现，6个替身测试通过
- ✅ Cursor ReadSeek 绑定完成，4个测试通过
- ✅ ReadSeek 九工具端到端接线完成，13个测试通过
- ✅ 完整测试套件 1839 个测试全部通过

**阻塞项**：
- 工具链版本不匹配（需要 Node v24.14.0, npm 11.19.1）
- 缺少 macOS/Linux arm64 机器
- 缺少 Live 验收配置

**建议**：
1. 安装正确版本的工具链
2. 生成新候选并运行冷重建
3. 取得 macOS/Linux arm64 机器验证
4. 配置 Live 验收环境

当前不建议批准交付，等待上述阻塞项解决。
