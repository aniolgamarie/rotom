# model-delegate 替换验收（mock）

当前仅记录源码和隔离 mock 证据。没有真实 Pi/Codex 调用、账号调用或原生通过结论；最终锁身份尚未冻结。

## 入口与来源清单：T087 完成

- 四配方依赖来源、plugin/skill 注册和资源声明均使用 model-delegate。pi-managed 使用 Task Keeper 的受管入口；该配置没有重新开放普通外部委托。
- 七个旧 Codex 角色转为 general/context/challenge/plan/research/review/scout 用途模板；没有旧角色的可执行注册。
- `caller-map.json` 对固定 starter 修订记录的 37 个匹配文件逐项给出处置和目标，全部目标存在。原始 blob 与冻结基线一致，调用方不依赖旧 shell 入口。
- 新源码中不存在旧 codex-agents 包或 codex-delegate 技能目录。历史名称只用于来源说明、格式历史和负向测试；未删除或改写旧机器目录。
- `validation_level=source-mapping-only` 继续准确描述调用方清单本身；测试通过另在这里记录，不把来源映射升级为真实执行证明。

## 本轮独立测试

2026-09-18 在默认隔离测试规则下执行：

| 命令 | 结果 | 范围 |
|---|---|---|
| `bash shared/skills/model-delegate/tests/test-contract-v2.sh` | 36 passed | V2 契约、上下文反馈、后端选择、旧入口缺席、两 backend × 七用途 |
| `bash shared/skills/model-delegate/tests/test-lifecycle-v2.sh` | 37 passed | 开始未知、幂等、取消、显式恢复、CLI、批次、原生事件替身和 Pi/Cursor 私有启动 |

第一次普通沙箱运行因 UID 映射导致临时目录祖先所有权校验拒绝；在正常 UID 下复验后全部通过。未放宽生产所有权检查。

## T088 的证据覆盖

| 场景 | 已有测试入口 |
|---|---|
| 只读调查、审查 | `test_pi_delegate_retirement.py`、`bridge.test.ts`、`delegate-pi.test.ts` |
| 显式写入及 Pi 写入拒绝 | `test_model_delegate_lifecycle.py`、`test_pi_delegate_native.py`、`delegate-pi.test.ts` |
| 后台启动、增量观察、终态等待 | `test_pi_delegate.py`、`test_model_delegate_lifecycle.py`、`external-executor.test.ts` |
| 取消与未知终止 | `test_model_delegate_lifecycle.py`、`test_pi_delegate_commands.py`、`external-executor.test.ts` |
| 显式恢复 | `test_model_delegate_lifecycle.py`、`test_model_delegate_cli.py` |
| 多模型比较和重复批次 | `test_model_delegate_batch.py`、`external-control.test.ts`、`external-executor.test.ts` |
| 反馈关联及伪证据拒绝 | `test_model_delegate_context.py`、`test_model_delegate_contract.py` |

已补齐真实插件→Runner→ExternalClient→RPC 的两 backend × 七模板、进度、取消与终态拒绝替身测试；同时修复旧运行时注册入口仍可派发的问题。委托、批次、控制、插件互斥和实际 manager 的定向 Node 28 passed，model-delegate 完整源码 TypeScript 检查通过。

控制矩阵对应验证：同一 manager 的执行上限与未知终止占位；managed 禁止普通外部派发；工具入口只读、显式 CLI 才可申请写入；单一压缩所有者与权限覆盖；重发幂等、不同 owner/候选/策略的旧凭证拒绝。完整默认回归的范围与时间边界见 `pi-web-foundation-mock.md`。

T088 代码/mock 完成。所有后端执行仍是替身，不据此确认官方 Codex CLI 的真实沙箱、Pi 原生加载或账号调用；这些保留在后续 native/live 任务。
