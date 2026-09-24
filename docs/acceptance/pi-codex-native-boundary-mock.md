# Codex 原生执行边界：隔离验证记录

日期：2026-09-17。层级：mock。真实Pi/Codex/DSH、登录及模型调用：not-run。

## 本次变更

- 官方Codex CLI仍通过exec/显式resume执行原生工具；默认路径不装载受控MCP IO替代层。
- 请求/收据绑定execution_boundary与execution_policy_digest；Pi为agentcfg-tools，Codex为native-sandbox，外部输入不能切换。
- Codex必须显式声明native_execution.allow_shell及tool_network=none。文件权限仍通过可表达性检查；部分write/create不能扩成完整目录写权限，command deny不能被丢弃。
- supervisor保存原生启动授权，绑定请求、运行时、lease/generation、cwd与编译权限。原生候选变化使用该授权、结果及终止证明，不要求MCP操作日志。
- 旧MCP文件/命令入口不供native-sandbox使用；MCP脚本和原型命令模块不进入默认冻结运行包。
- 策略失配请求停止整次运行，确认终止前保持写锁。Task Keeper逐请求/逐工具边界未放宽。

## 已执行

1. `.venv/bin/python -m pytest -q`：1104 passed，7 subtests passed，198.21s。
2. 最后补充冻结策略schema校验后，`tests/test_pi_delegate_native.py`、`test_model_delegate_contract.py`、`test_model_delegate_backends.py`、`test_model_delegate_cli.py`、`test_pi_delegate_files.py`：36 passed，9.59s。
3. `node scripts/test-pi-mock.mjs agents/pi/runtime/tests/delegate-pi.test.ts agents/pi/runtime/tests/external-executor.test.ts agents/pi/packages/model-delegate/tests/bridge.test.ts`：15 passed。
4. 临时源码副本的subagents-vendor `tsc --noEmit`通过；`node --check agents/pi/runtime/delegate-pi-main.ts`通过。
5. Python compileall、git diff --check、修改文档的相对链接与围栏检查通过；任务112个且ID唯一，76个已勾保持不变。

各组有重叠，不累计为独立测试数。测试使用临时HOME、虚构模型/授权、假进程及候选文件；原生编辑正向用例由替身修改候选，证明控制者的结果分类，不能证明OS沙箱本身。

## 关键用例

| 场景 | 已观察结果 |
|---|---|
| 候选原生编辑、没有MCP日志、有本次授权及终止证明 | completed/verified-execution；源文件哨兵未变 |
| 结果文本存在、原生启动授权缺失 | failed/unverified |
| 认证完成后删授权再读结果 | 在线/离线授权校验不再接受缺失凭证 |
| 错边界、错策略、早期V2缺字段 | 拒绝，不补默认值认证 |
| native-sandbox调用受控文件RPC或原型命令入口 | 拒绝 |
| 当前原生授权失配，进程仍活着 | cancel_requested，generation撤销，写租约保持 |
| 默认冻结包 | 无MCP脚本/原型模块；包含原生授权模块 |
| Pi试图改为native-sandbox | SDK会话创建前拒绝 |

## 未覆盖与交付门槛

固定CLI实际参数、各平台原生工具与沙箱、源checkout/越界拒绝、真实子工作终止、系统/企业配置和附加资源发现、真实登录/模型/代理行为均未获本次native/live证明。
默认模型工具仍只读；高级implement仍需三项显式准入。缺少新边界字段的旧V2记录保留但不自动认证/恢复。
本记录不宣布T074完成、Pi迁移完成或release gate通过。

### 前一阶段的保守拒绝（已由机器根投影替代）

原生投影不能丢弃非project根的file deny；当前无法表达时直接拒绝。
机器级permissions.readonly_roots/denied_roots尚未完成原生投影，非空时同样阻止Codex准入，不能静默略过。
这是明确的能力缺口，不是已实现这些机器根规则。该项仍需后续投影与平台验证。
补充后backend/native组合16 passed（4.20s），包含删除授权后的离线拒绝断言；静态检查再次通过。

机器根投影的后续实现与最新1117项回归见[独立记录](pi-native-root-projection-mock.md)；上段的“一律阻止”是历史状态。
