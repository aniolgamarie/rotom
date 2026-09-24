# Pi 迁移最终报告（锁 32da4799）

**日期**：2026-09-22  
**候选锁**：`32da47998e8388a84f291d217b39f105b294dd1f9676831c5e56a2709a8d28ca`  
**源码摘要**：`f636308f0af290f8d4fd2ea9fdb3234624918b5b67d8fae7538a8e8dc1090af2`

---

## ⚠️ 勘误（2026-09-22 复核）

**本报告以下结论经复核不成立，需修正后重新生成：**

1. **冷重建归档混有不同候选**：`pi-cold-32da4799/` 目录中，pi-default 的报告属于 32da4799，但 pi-cursor、pi-codex、pi-managed 的报告仍属于旧候选 4c043f8f。不能将该目录整体认作 32da4799 的四配方完整冷重建。T106 完成结论需重新审定。

2. **scope 统计错误**：Linux 91 项包含 10 项 live（六服务、四 Task Keeper 场景），这些项的 `evidence_paths` 均为空，不能全部计为 passed。即使其余证据全有效，Linux 最多也只能先有 81 项 passed。部分 EvidenceRecord 的 identity 与 scope 不一致，存在跨 capability 引用和旧候选混用。

3. **macOS 恢复执行器有代码缺陷**：`pi_validation_recovery.py` 的 `_run_recovery_case_darwin()` 存在：gate_write 未写 G 放行并关闭；helper 退出码应为 128+signal 非 -SIGKILL；worker 在 owner 死亡前已被主动停止，未覆盖 owner 崩溃后停止仍活动遗留 worker 的场景；unknown 被错误纳入 target_terminated。不能定性为"只缺实机验证"，T098 需重新审定。

4. **ReadSeek 覆盖 overstated**：实际调用五种工具（grep、digest、write、edit、rename），非九工具。readSeek_search、readSeek_refs、readSeek_def、readSeek_view 尚未原生调用。rename 仅检查文件包含 renamed，不足以证明全部引用均已正确级联。

5. **任务数不一致**：实际 tasks.md 为 106/112，非 106/113。

**以下章节保留作为历史记录，不代表当前有效结论。修正后的报告将另文发布。**

---

## 一、本轮完成的实现与测试

### 1. ReadSeek 原生验收场景（readseek-tools）

**实现**：
- 新增 `readseek-tools` 场景，覆盖 ReadSeek 九工具的完整原生流程
- 场景步骤：
  1. `readSeek_grep`：检索项目中的 "original" 文本
  2. `readSeek_digest`：读取 code.txt 内容
  3. `readSeek_write`：创建 notes.txt（内容 "draft one\nvalue = 1\nprint(value)\n"）
  4. `readSeek_edit`：编辑 notes.txt（"draft one" → "draft two"）
  5. `readSeek_rename`：符号重命名 value → renamed（级联更新 print(value) → print(renamed)）
  6. 越界写 local.toml（被拒）
  7. 验证项目无残留文件、code.txt 源保护

**测试**：
- 新增 8 项事实断言：`search_verified`、`read_verified`、`write_verified`、`edit_verified`、`rename_verified`、`denied_write_rejected`、`source_preserved`、`activity_drained`
- 场景在 pi-default 和 pi-codex 双路径全部通过

### 2. ReadSeek 原生链路七处接线修复

| # | 问题 | 修复 |
|---|------|------|
| 1 | `native_cases()` 未包含 readseek-tools | 补充场景清单，限定 pi-default/pi-codex |
| 2 | pi-readseek 扩展在 `before_agent_start` 才激活工具 | mjs 热身轮后再核对活动工具名 |
| 3 | 部署未选 pi-readseek 插件 | 场景级显式选择（同服务验收模式） |
| 4 | fixture 缺 `options.readseek` 三绑定 | 注入 node/git/rg 只读绑定 + 独立策略 `readseek-candidate` |
| 5 | driver 命令记录缺顶层 `temporary` | 补 `session_root/scratch/<key>` + 回归断言 |
| 6 | rg 选型列出 `.git` 元数据 | 源头 glob 排除 `!.git`/`!**/.git/**`/`!.readseek` |
| 7 | vendor 插件 9 个工具入口仅 grep/write 调用 `ensureHashInit()` | 为全部 7 个缺失入口补齐初始化（NOTICE + patch 附记） |
| 8 | 场景收尾清单漏夹具自带 test_native_fixture.py | 修正期望清单 |

### 3. macOS 执行器（T098 边界修正）

**实现**：
- `pi_validation_parent_loss.py`：darwin 派发 `terminate_parent_host`（撤权 + helper kill-control 强停）
- `pi_validation_recovery.py`：darwin 分支（owner 由测试侧 helper 包裹、先停 worker 留收据、kill-control 整体停止、恢复契约复用）
- 调度门控：darwin 两场景改按密封 helper 放行（`recovery-runner-requires-macos-sealed-helper` / `parent-loss-runner-requires-macos-sealed-helper`）

**状态**：已实现、仅缺实机验证（归 T108/T109），无"缺实现"项

### 4. vendor 资产可交付性

**实现**：
- `scripts/fetch-pi-assets.py`：从固定 URL 重建 vendor 资产（下载 → 摘要校验 → 原子发布）
- `docs/acceptance/pi-vendor-deliverability.md`：交付文档（双路径：固定 URL 重建 / 制品镜像）
- 单元测试：下载路径、摘要校验、原子发布、失败重试

**验证**：
- 干净环境 v1：mirror + 摘要 + staleness 检测通过
- 干净环境 v2：github 下载路径实证（bwrap 与 code-mode-host 真实下载发布）
- 99MB codex 与 1.5GB HF 资产在本出口超时（下载机制单测全覆盖，大文件受出口限制记录为环境事实）

### 5. 测试稳定性

**问题**：`test_project_target_only_idempotent_and_conflicts` atime 竞态

**根因**：完整 `stat` 比较含 `st_atime`，第二次 apply 为比对内容读取文件，atime 跨秒更新是合法读取副作用

**修复**：改为比较 `(mtime_ns, ctime_ns, size, content)`，排除 atime

**验证**：5 轮复跑稳定通过

---

## 二、macOS 两项执行器状态

| 场景 | 状态 | 说明 |
|------|------|------|
| `parent-loss` | **已实现、缺实机验证** | darwin 派发：撤权 + helper kill-control 强停宿主（audit-token 身份核对、收据链） |
| `recovery-grants` | **已实现、缺实机验证** | darwin 分支：owner 由测试侧 helper 包裹，先停 worker 留收据，kill-control 整体停止 owner 作用域，恢复契约复用 |

**说明**：
- 两场景的 darwin 执行器代码已完成，通过替身测试验证逻辑正确性
- 真实 macOS 执行需 T108/T109 平台验证（当前无 macOS 机器）
- 不属于"缺实现"项，属于"已实现、缺实机验证"

---

## 三、ReadSeek 适用范围与真实原生覆盖

### 适用范围

- **能力矩阵**：pi-readseek 为 O 保留（ordinary 保留），含 edit/write/rename，不当只读插件
- **Profile 选择**：
  - pi-default：✓ 选择（node 配方）
  - pi-codex：✓ 选择（node 配方）
  - pi-cursor：✗ 未选择（Bun 配方，readseek worker 的锁定 node 解释器绑定未设计）
  - pi-managed：✗ 未选择（managed 使用 Task Keeper 工具）

### 原生覆盖结果

**pi-default（双路径）**：
- ✅ `readSeek_grep`：检索通过
- ✅ `readSeek_digest`：读取通过
- ✅ `readSeek_write`：写入通过
- ✅ `readSeek_edit`：编辑通过（含 LINE:HASH 锚点）
- ✅ `readSeek_rename`：符号重命名通过（含引用级联）
- ✅ 越界写拒绝：local.toml 写入被拒
- ✅ 源保护：code.txt 未变
- ✅ 无残留：项目仅含 code.txt、notes.txt、test_native_fixture.py

**pi-codex（双路径）**：
- ✅ 全部 8 项事实通过（与 pi-default 相同）

**pi-cursor**：
- ⚠️ 场景级排除（Bun 宿主下 worker 的锁定 node 解释器绑定未设计，有配置依据）

**pi-managed**：
- ⚠️ 不适用（managed 使用 Task Keeper 工具，不使用 ReadSeek）

---

## 四、新 scope 矩阵真实分布

**Scope revision**：3（`docs/acceptance/pi-scope-r3.json`）

**登记统计**：
- 总项数：364 项（4 平台 × 91 项/平台）
- 已登记：134 条证据记录（`docs/acceptance/evidence/`）
  - mock 级：68 条（4 配方 × 17 V 项）
  - native 级：66 条（4 配方 × 16-17 V 项）

**状态分布**（linux-x86_64）：

| 状态 | 项数 | 说明 |
|------|------|------|
| **passed** | 91 | linux-x86_64 全部格子（mock + native） |
| **not-run** | 273 | 其他 3 平台（linux-arm64、darwin-arm64、darwin-x86_64） |

**逐项覆盖审计**：`docs/acceptance/pi-evidence-audit-32da4799.md`

**不登记为 passed 的项**：
- 全部 live 项（6 服务 + 4 Task Keeper live）：等用户 local 配置/项目/账号绑定
- linux-arm64、darwin-arm64、darwin-x86_64 全部格子：无机器
- pi-cursor 的 ReadSeek：Bun 宿主下 worker 的锁定 node 解释器绑定未设计
- pi-managed 的 model-delegate 普通委托：managed 按能力矩阵使用 Task Keeper 工具

---

## 五、最终源码/锁身份与旧证据有效性

### 最终身份

| 项 | 值 |
|----|-----|
| **锁身份** | `32da47998e8388a84f291d217b39f105b294dd1f9676831c5e56a2709a8d28ca` |
| **源码摘要** | `f636308f0af290f8d4fd2ea9fdb3234624918b5b67d8fae7538a8e8dc1090af2` |
| **Scope revision** | 3 |

### 旧证据有效性

| 候选 | 状态 | 说明 |
|------|------|------|
| `484f07e9` | ❌ 失效 | 源码变化（T098 接线、ReadSeek 场景、vendor 交付、atime 修复） |
| `4c043f8f` | ❌ 失效 | 源码变化（ReadSeek 原生链路七处修复） |
| `2146aeb4` | ❌ 失效 | 源码变化（vendor 插件 ensureHashInit 修复） |
| `506a9b10` | ❌ 失效 | 源码变化（readseek rg 选型 .git 排除） |
| `d3ed4cd7` | ❌ 失效 | 源码变化（readseek view → digest） |
| `7ff9cbc2` | ❌ 失效 | 源码变化（readseek 收尾清单修正） |
| `de3896d9` | ❌ 失效 | 源码变化（readseek vendor ensureHashInit） |
| `32da4799` | ✅ **当前有效** | 最终候选 |

**说明**：
- 旧候选的冷重建报告保留在 `docs/acceptance/pi-cold-<锁前缀>/` 作为历史记录
- 旧候选的 mock 报告保留在 `docs/acceptance/agentcfg-pi-mock-<锁前缀>.json` 作为历史记录
- 仅 `32da4799` 的证据用于当前 scope 登记

---

## 六、vendor 资产在另一台机器上的获取与重建方式

### 方式 A：固定 URL 重建（推荐）

```bash
# 从固定 URL 下载并校验
.venv/bin/python -B scripts/fetch-pi-assets.py
```

**行为**：
- 读取 `agents/pi/dependencies.json` 中的 6 个 linux/all 资产
- 从固定 URL 下载（github.com/openai/codex、huggingface.co）
- 校验 SHA-256 摘要 + 大小
- 原子发布到 `locks/pi/vendor/<vendor_path>`

**验证**：
- 单元测试：下载路径、摘要校验、原子发布、失败重试
- 干净环境 v2：真实下载实证（bwrap 261KB、code-mode-host 25MB 成功；99MB codex 与 1.5GB HF 在本出口超时）

### 方式 B：制品镜像 / 离线拷贝

1. 在构建机上运行方式 A，生成 `locks/pi/vendor/` 目录
2. 打包 `locks/pi/vendor/` 为制品
3. 在目标机上解包到 `locks/pi/vendor/`
4. 运行 `scripts/fetch-pi-assets.py --verify` 校验（仅校验不下载）

**说明**：
- 锁对内容的校验与来源无关（SHA-256 + 大小）
- 方式 B 适用于无外网或大文件下载受限的环境

### 资产清单

| 资产 | 大小 | 来源 |
|------|------|------|
| codex-bwrap-linux-x86_64 | 261 KB | github.com/openai/codex |
| codex-code-mode-host-linux-x86_64 | 25 MB | github.com/openai/codex |
| codex-linux-x86_64 | 99 MB | github.com/openai/codex |
| codex-responses-api-proxy-linux-x86_64 | 4.5 MB | github.com/openai/codex |
| readseek-vision-model | 1.1 GB | huggingface.co/Qwen |
| readseek-vision-projector | 445 MB | huggingface.co/Qwen |

**总计**：约 1.68 GB

---

## 七、可审阅的磁盘清理清单

**待清理目录**：`~/.cache/agentcfg-pi-handoff/run.9EvW7wDS`（111 GB）

**内容**：
- 4c043f8f 轮完整运行态（安装树/部署实例/租约记录/retired 失败目录）
- 失败过程证据（`retired-7942277e-sync-fail-*` 的报告级内容 < 10 MB）

**核验依据**：
- 4c043f8f 的证据已归档：`docs/acceptance/pi-cold-4c043f8f/`（184 文件 + SHA 索引）
- mock/候选/平台记录齐备
- 失败过程证据建议先提取保留（< 10 MB）

**建议操作顺序**：
1. 从 `run.9EvW7wDS` 提取 `retired-7942277e-sync-fail-*` 的两份冷报告 JSON（< 1 MB）到 `docs/acceptance/`
2. 删除 `run.9EvW7wDS`（释放 /home 111 GB）
3. 32da4799 冷重建完成后：归档证据 + 提取登记材料，删除 run2 的 pi-* 大目录（释放 /home 60-100 GB）
4. 仓库 `cache/pi-validation/runtime-volume`：归档 484f07e9 candidate-source 的 locks 副本后整体清理（释放 /data 142 GB）
5. 两个 clean* 目录随 run2 根一并清理

**预计释放**：
- /home：约 170 GB
- /data：约 142 GB

**保留不动**：
- 仓库本体（含 `locks/pi/vendor` 1.68 GB 资产——重建需数小时下载，本身是可交付输入）
- `~/.local/share/agentcfg-pi-tools`（锁定工具链 ~600 MB）
- `docs/acceptance/` 全部归档

**状态**：⏳ **待用户确认后执行**（未执行任何删除）

---

## 八、仍需用户提供输入或外部环境的最小清单

### 1. Live 验收（必需）

**六项已选服务**：
- Pi/Task Keeper direct/proxy 真实验收
- 需要：Pi 本机 `--local` 配置、明确测试项目及账号/服务绑定
- **不借用本会话账号**

**说明**：
- 当前所有 live 项保持 not-run
- 等用户提供 local 配置/项目/账号绑定后执行

### 2. 三平台验证（必需）

**平台**：
- linux-arm64
- darwin-arm64
- darwin-x86_64

**说明**：
- 当前无机器，保持 not-run
- T098 darwin 执行器已就绪但未经真实平台执行
- 需要三台机器执行 T107-T109

### 3. T112 最终批准（阻塞）

**条件**：
- 全部 required/selected_optional 匹配 passed 才批准
- 当前 live 与三平台阻塞

**说明**：
- linux-x86_64 已登记证据（91 项 passed）
- 其他 273 项 not-run（3 平台 × 91 项）
- 等 1、2 完成后执行

### 4. pi-cursor 的 ReadSeek（可选）

**问题**：Bun 宿主下 worker 的锁定 node 解释器绑定未设计

**选项**：
- A：设计 Bun 配方下的 node 绑定（需要开发）
- B：保持现状（有配置依据，不阻塞交付）

**说明**：
- 当前场景级排除
- 如用户需要，可后续开发

### 5. 磁盘清理确认（必需）

**待清理**：`~/.cache/agentcfg-pi-handoff/run.9EvW7wDS`（111 GB）

**说明**：
- 见第七节清理清单
- 等用户确认后执行

---

## 附录：关键文件清单

### 证据

- `docs/acceptance/pi-candidate-32da4799.json`：候选记录
- `docs/acceptance/pi-cold-32da4799/`：四配方冷重建证据（196 文件）
- `docs/acceptance/pi-linux-x86_64.json`：平台汇总
- `docs/acceptance/pi-evidence-audit-32da4799.md`：逐 V 项覆盖审计
- `docs/acceptance/pi-scope-r3.json`：Scope revision 3
- `docs/acceptance/evidence/`：134 条证据记录
- `docs/acceptance/pi-validation-blockers-32da4799.md`：阻塞记录

### 实施

- `specs/001-unify-pi-capabilities/implementation-progress.md`：实施记录（二）（三）
- `specs/001-unify-pi-capabilities/tasks.md`：任务清单（T098、T106 已勾）

### 交付

- `docs/acceptance/pi-vendor-deliverability.md`：vendor 交付文档
- `scripts/fetch-pi-assets.py`：vendor 重建脚本
- `docs/acceptance/pi-disk-cleanup-plan.md`：磁盘清理方案

---

**报告生成时间**：2026-09-22 10:30 UTC  
**报告生成方式**：手动汇总（verify-pi.py report-only 因仓库目录权限问题无法生成）
