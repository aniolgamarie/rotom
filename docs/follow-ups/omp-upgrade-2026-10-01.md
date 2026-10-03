# OMP v18.4.5 升级评估与执行计划

评估与执行日期：2026-10-01。升级已完成，最终证据见 [v18.4.5 升级验收](../acceptance/omp-upgrade-18.4.5.md)。以下保留最初评估和计划，并明确执行后的验证边界。范围为官方运行包、仓库自有适配器与独立权限插件；禁止修改上游源码、二进制或通过私有接口改写宿主。

## 评估时状态与证据（部署前）

| 状态 | 工作 | 证据或边界 |
|---|---|---|
| 已完成 | 开启工具活动显示 | `profiles/omp-kernel.toml` 的 `display.hideToolActivity=false`；参考夹具同步更新 |
| 已完成 | 同版本离线刷新依赖锁与 sync | 仍为 v18.3.0 / `62bc57be1b03ef0802a33cf7f5f530e534527531`，运行包、插件、上游材料均未变；新锁 `e7fc05e2e8d036396140bf6dbbf277cb674cfc63cae6f7b88f15d22e561d0d05` |
| 已完成 | 配置回归 | `pytest -q tests/test_omp_kernel.py --tb=short`：14 passed；首次沙箱运行被 UID/文件属主映射阻止，重跑不改变测试内容 |
| 失败待决策 | 日常实例显示配置 apply | 管理器返回退出码 4：活动 OMP 进程；等待用户退出，不自动终止，不直接写原生配置绕过检查 |
| 已完成 | 最近 Cursor 错误分类 | 2026-10-01 10:19:04（+08:00）`cursor/kimi-k3-high` 超时；11:05:10 通用 provider 响应错误；之后 `kimi_tf/k3` 中止。只输出脱敏分类，没有账号数据或会话正文 |
| 已完成 | 核对最新稳定版本 | 官方 latest 指向 v18.4.5；release 标记 2026-09-30；提交链接指向 `79808c3bf8f8cd9826decc63e3e18b13035f64f8` |
| 环境不足未验证 | 新版兼容性与 Cursor 故障消除 | 尚未下载新版完整材料、执行新版类型检查或启动新版宿主；没有真实模型请求 |

日志只能证明本地请求失败，不能证明服务端从未接受请求，亦不能把随后中止当作 fallback 成功。当前证据不足以确认认证、代理、HTTP/2 或版本是唯一根因。执行模型传输与权限主审不支持 Cursor OAuth 后进入远程 API fallback 是不同路径。

## 升级收益与需要验证的变化

官方 [v18.4.5 发布说明](https://github.com/can1357/oh-my-pi/releases/tag/v18.4.5)记录了 Cursor 的 HTTP/1 transport fallback、断流 checkpoint 恢复、结构化错误，以及保留已完成工具结果的重试修复。模型发现改为账户 catalog，包含模型能力与 effort 信息，并修复跨账户缓存。因此升级值得验证，但发布说明不能证明本机故障已经解决。

[v18.3.1 发布说明](https://github.com/can1357/oh-my-pi/releases/tag/v18.3.1)还包含 provider 禁用设置和 layered settings 的修复；升级必须回归配置来源隔离与持久化行为。当前仓库动态 `DISABLED_PROVIDERS` 已排除 Cursor；仍需核验部署产物与发现清单一致，不能直接沿用历史静态文件或假定禁用行为不变。

独立插件使用公开 `registerTool`、工具集合操作、会话事件与 `omp.exec`。现阶段没有证据要求宿主补丁；必须以新版 SDK 类型和实际接口测试确认兼容。

## 执行步骤与验收门槛

1. **准备固定官方材料。** 再核对 latest；本计划目标固定 v18.4.5，不追踪 main。取得完整 tag/commit 身份、不可变源码归档、官方校验清单与四个平台 standalone 资产摘要；核验实际归档和所需二进制字节。临时材料不得覆盖日常运行包；不执行上游安装脚本或构建补丁宿主。

2. **调整仓库自有适配。** 更新 `src/agentcfg/omp_dependencies.py` 的版本、commit、source/assets 摘要，`src/agentcfg/omp.py` 的依赖说明，`agents/omp/plugins.toml` 的兼容声明，以及权限插件 `package.json` 中 SDK 身份。新版本有接口变化时只调整本仓库插件调用公开 API 的方式。更新 `locks/omp/upstream/` 的完整材料与普通 manifest，复算 package tree、recipe、resources 和 identity。旧 patched manifest、补丁与历史模型评测只保留历史身份，不改写为新版通过证据。

3. **确认 Cursor 模型身份。** 新版账户 catalog 可能改变旧 effort lane 的表示；不得假定 `cursor/kimi-k3-high:high` 永远有效，也不得静默替换成 Auto。通过公开模型发现核对当前账户中的 ID 与 effort，再明确映射私人 `native_model_roles.main`。审批 reviewer/remote fallback 保持单独配置，执行模型升级不代表权限插件已支持 Cursor OAuth 审查。

4. **离线验证。** 运行 kernel、adapter、discovery、dependencies、permission runtime 和事务相关现有测试；使用临时 HOME、假 provider/子进程并阻断网络。针对新版 SDK 做插件严格类型检查与 bundle。验证 active tools 替换、session start/switch/branch/shutdown、pending abort、`omp.exec` 的超时/取消/退出码、原生 deny/prompt 下限与远程 fallback。对 Cursor 重试与工具结果保留使用离线 fixture，避免重复执行。仅修改显示开关不能代替上述升级验收。

5. **隔离新版宿主验证。** 真实宿主 smoke 是单独授权步骤，使用临时 HOME、固定本地假 provider 与无害命令，验证插件加载和执行行为，不读取真实账号、不发付费请求。离线及隔离宿主通过后，才进行真实账户 catalog 与最小 Cursor 请求验证。历史模型预算已用尽；新请求需要单独预算，不能沿用历史质量报告证明新版通过。

6. **部署日常实例。** 用户退出实例后，检查无活动进程、无恢复待办与所有权冲突。在私人目录一致备份需要保留的账号数据库、会话、原生配置和部署记录，不将秘密写入仓库或通用日志。执行 `sync → plan → apply → doctor`，检查配置漂移、模型映射和审批 sidecar。不得通过原生自更新旁路 agentcfg 的锁。同步 `docs/omp-dependencies.md`、`docs/omp-kernel.md` 与当前验收材料。

7. **验证恢复边界。** 保留旧官方二进制及部署身份；验证配置回滚不会丢失用户会话和非受管字段。数据库若发生迁移，不能仅回退二进制就声称恢复成功：须确认旧版兼容性或按经过验证的备份恢复流程处理，且不得覆盖新版产生的会话而不作明确处理。

## 范围边界

升级本身不会自动增加 `permission_bash` 的自定义渲染器、原生后台 job/reap 能力或可调用的本地 tiny 审查。这些属于独立功能工作；公开 API 不足时说明限制，不扩展到宿主补丁。

## 执行完成后的状态

用户授权升级，并在活动实例锁阻止备份后确认已退出。已完成固定官方材料、仓库适配与 schema 更新、离线锁重算、新版 SDK 严格类型检查、插件 bundle，以及最终身份的隔离官方宿主 smoke。没有修改 agent 上游源码。

管理器最终完整回归为 228 passed、7 skipped，跳过项是退役的历史补丁宿主验证。插件测试为 315 passed、0 failed、1152 assertions。隔离宿主仅请求 loopback 假 provider，主审失败后远程 fallback 接替一次，`permission_bash` 执行一次无害 `ls -la`，新会话恢复 smart；付费模型请求为 0。

一致私人备份完成后，日常实例已执行 `sync → plan → apply → doctor`。最终锁为 `14480cb8a99390aa3cc47df5fbdd4087c898d9e8e77e0eccf176bf383beb4f22`，Linux x64 运行包追加 `-linux-x64`。受管 `--version` 输出 `omp/18.4.5`；doctor 为 offline-ready、待变更 0，无漂移、冲突和恢复待办。工具活动显示已开启，执行模型与审批选择保持分别配置。80 份非受管原生文件与备份字节一致，包含账号与会话文件。

当前没有进行中或失败待决策的升级工作。真实 Cursor 请求、账户 catalog 核验和其他平台真实运行仍为环境不足未验证；没有用发布说明替代故障消除证据。旧二进制与私人备份保留，但跨版本回退需要匹配的仓库版本元数据、锁和部署状态；数据库回退兼容性未经验证。

2026-10-02 后续：受管模型字段出现成员 ID 与新版逻辑 ID 的名称漂移，已将本机 `native_model_roles.main` 从 `cursor/kimi-k3-high:high` 对齐为 `cursor/kimi-k3:high`，high wire route 保持同一成员模型。`plan/apply/doctor` 与用户项目目录启动准入均通过，未放宽漂移保护，未发送模型请求。详见[升级验收后续记录](../acceptance/omp-upgrade-18.4.5.md#2026-10-02模型名称对齐)。
