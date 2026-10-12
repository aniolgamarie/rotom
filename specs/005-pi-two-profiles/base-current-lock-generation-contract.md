# Base 正式兼容声明的受控锁生成

2026-10-09 root 决策，T009/T010 的默认实现子包。现有 `read_inputs` 只接受 candidate，`read_lock` 已能严格读取 current 与 accepted；直接放松输入会改变所有普通生成调用。本包采用显式调用参数，默认行为保持候选生成，暂不接 CLI、不发布本仓库正式锁、不修改任何真实 provider 的 verified 版本。

## 接口与不变量

`PiBackend.resolve_lock(repository, *, current_profiles=())` 将参数传至自有 `pi_vendor.resolve_lock` 和 `read_inputs`。仅现代家族允许非空参数；参数必须为确切 tuple，元素是互不重复的确切字符串 `pi-base`/`pi-full`，且必须为本次真实声明的 profile。错误为固定 ConfigError，禁止参数值或异常原文进入消息。所有旧调用省略参数，仍只接受 candidate。

参数只允许读取已经由维护者声明为 current 的所选 profiles，不重写状态或兼容性。参数中的 profile 必须恰为 current；未选择的 profiles 必须为 candidate。accepted 无论参数如何始终不能由生成器发布，也不接受任何 acceptance digest。generation 不是部署、激活、外部验收控制面或模型权限入口。

`read_inputs` 在工具版本检测、npm、归档或发布之前，除既有闭合 binding 校验外，对所选 current profile 检查固定 pi-host version 在每个所选 provider 的 `verified_host_versions` 中，且 profile engine 在每个所选 provider 的 engines 中。candidate_host_versions 不能替代 verified。禁止自动补版本、换 provider、丢未知字段或从参数生成证明。真实来源身份、资源与完整解析图继续由原 generator/readback 校验；本包不重写它们。

在原发布前校验处，candidate 仍允许未解决的许可证材料；current 必须使用与 read_lock 相同的严格许可证模式。任何兼容、来源、资源或许可证失败不得改写原发布 manifest 或旧 pair。声明修改本身会使旧锁的 recipe context 过期，原 read_lock 必须继续拒绝它；只有在原绑定输入恢复后，旧锁才应保持可读。默认失败测试先核旧锁字节未变，再仅在合成 fixture 中显式恢复原输入做严格回读，不把该测试操作称为生产恢复。沿用现有切片不可变路径和 manifest 最后原子替换，不引入新事务/锁/恢复语义。

成功生成的 current 锁必须由原 `PiBackend.read_lock` 严格回读并返回 current 的 validated selection。Base/Full 的声明与切片照旧分开；本包不开放 Full 或更改实际两 profile 的 candidate 声明。新的来源或选择状态改变身份，已有候选证据不得冒充新 current RuntimeIdentity 或产品验收。

## 默认验证

唯一代码写入者负责 `src/agentcfg/pi_vendor.py`、`src/agentcfg/pi_dependencies.py`、`tests/test_pi_lock_families.py`；报告和即时前像在独立小目录。先保存 preimage，增加真实默认 red，再实现并运行受影响 green。复用当前合成 generator fixture、虚构来源和 fake npm，不联网、不启动第三方宿主、不导入 SDK、不部署。

覆盖 current 实际序列化生成并原回读、默认调用拒绝 current、参数与声明/家族/profile 不一致在 resolver 前失败、缺 verified 或错 engine 在 resolver 前失败、accepted 永远拒绝，以及严格许可证失败时完整旧锁字节未变、recipe 过期被拒、恢复原 fixture 输入后严格回读。原候选生成与其 sync 前拒绝保留；不把没有运行的安装/宿主/原生检查记为通过。通过后停止写入，再对稳定 diff 做独立复核；只有发现新问题才扩大检查。

本包只提供受控生成接口和默认证据。真实 provider lifecycle/UI/业务兼容仍待测，当前正式 8/100、无 formal manifest/seal/activation，AUTO OFF。
