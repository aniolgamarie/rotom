# Implementation Progress

## 2026-09-10 Session (Updated)

### 进度回填修复 ✓

1. **撤销 10.2/12.1 的提前完成标记**
   - Task 54 (10.2): 逐请求gate认证 - 恢复为未完成
   - Task 65 (12.1): 故障溯源更新 - 恢复为未完成

2. **修正 TK11 跨层复制**
   - 移除 TK11:A 和 TK11:E 的 S 层复制证据（12行）

3. **修正零断言证据**
   - 移除 9 个 attributed_assertions=0 的错误证据
   - 涉及义务：CFG-013:U, EVD-013:U, RTB-008:U, T22:U, T29:U, T46:U, T49:U, T67:U, T76:U

4. **修正旧 hash**
   - 使用 report.json 的 lockDigest: 2aea53268675b220714c556bb563f3f822a1a178bf86a70a6afbbe8b2eec74a8
   - 更新 runtime-progress.json 的 runtimeLockDigest

5. **恢复 P4 延期**
   - 排除 T66, T68, T69 的 6 项 P4 义务
   - P0-P3 missing 从 106 修正为 100

6. **统一为 P0–P3 缺 100 项的准确检查点**
   - runtime-progress.json: fullMissing 只包含 P0-P3 义务
   - missingCount: 100

### 当前状态

#### 任务进度
- Total: 76
- Complete: 71
- Remaining: 5
  - Task 37 (7.4): Qwen smoke test - 阻塞（需要 Qwen binding）
  - Task 54 (10.2): 逐请求gate认证 - 待完成
  - Task 64 (11.6): 参数化对照 - 阻塞（需要真实模型执行环境）
  - Task 65 (12.1): 故障溯源更新 - 待完成
  - Task 73 (13.5): 恢复验收 - 阻塞（需要 Qwen binding）

#### 义务缺口（P0-P3）
- Total: 100
- By category:
  - needs_impl_or_review: 5 (需要实现 U 层级测试文件)
  - needs_layer_check: 82 (78项有其他层级证据，4项完全没有证据)
  - needs_live_binding: 6 (阻塞，需要 Qwen binding)
  - needs_oracle: 7 (需要实现 V 层级测试文件)

#### 矩阵缺口
- Total: 313
- await-orders: 158 (S 30 / A 64 / E 64)
- crash-cuts: 65 (S 11 / A 18 / P 18 / E 18)
- request-paths: 90 (S 42 / A 24 / P 24)

#### 测试结果
- Tests: 788 passed, 0 failed
- Assertions: 17,250
- releaseReady: false

### 需要实现的测试文件

总共需要实现约 16 个测试文件：

#### U 层级 (5个)
- tests/cases-g18-u.test.ts (CFG-001:U)
- tests/cases-g14-u.test.ts (REC-012:U)
- tests/cases-g30-u.test.ts (VAL-001:U)
- tests/cases-g26-u.test.ts (T43:U)
- tests/cases-g25-u.test.ts (TK08:U)

#### V 层级 (7个，可能合并为 4-5 个文件)
- tests/cases-g30-v.test.ts (VAL-001:V, VAL-006:V, VAL-008:V)
- tests/cases-g32-v.test.ts (VAL-005:V, VAL-007:V)
- tests/cases-g04-v.test.ts (VAL-011:V)
- tests/cases-g09-v.test.ts (VAL-015:V)

#### 其他层级 (4个)
- tests/cases-g01-e.test.ts (CFG-011:E)
- tests/cases-g25-p.test.ts (SCH-010:P)
- tests/cases-g25-e.test.ts (SCH-010:E)
- tests/cases-g04-a.test.ts (VAL-011:A)

### 验证命令

所有验证命令通过：
- typecheck: exit 0
- plan: passed (126 scenarios, 102 faults, 228 obligations)
- openspec validate --strict: valid
- check-design.py --self-test: 707 P0-P3 designed, 0 unmapped
- git diff --check: clean

### 阻塞项

1. **W6 Qwen实网** (Tasks 37, 64, 73)
   - 需要用户提供 Qwen binding 参数
   - 包括 profile 路径、provider/model/account/network 引用、总请求上限等

2. **needs_live_binding** (6项义务)
   - VAL-005:A, VAL-005:E, VAL-005:L
   - VAL-007:A, VAL-007:E, VAL-007:L
   - 需要真实 Qwen 绑定才能完成

### 下一步工作

1. 实现 U 层级测试文件 (5个)
2. 实现 V 层级测试文件 (4-5个)
3. 实现其他层级测试文件 (4个)
4. 处理 needs_layer_check 中的 78 项（已有其他层级证据）
5. 补齐矩阵缺口 (313项)
6. W3-W5 实施

### 注意事项

- 保持冻结范围，不新增组合
- 不把映射完成当验收完成
- Qwen 实网及效果对照单列等待配置与预算
- 涉及入口/调度/存储重构时，需连同对应集成回归实施
