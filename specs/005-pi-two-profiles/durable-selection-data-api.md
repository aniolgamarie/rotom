# 显式选择数据校验接口

2026-10-07 root 选择的有限实现包。前置是已接受的共享 resolution 与 header 兼容提取；本包只复用原选择计算，不创建 installed 来源、权限或 activation。

## 唯一新公开接口

在原 `pi_capabilities.py` 增加：

```python
validate_selection_data(catalog, providers, selection, metadata, *,
  lock_identity, host_version, engine, accepted_binding_digest=None)
```

返回原 frozen `ValidatedSelection` 的全部十字段。metadata 与 lock_identity 是显式、稳定的解析数据，不借 PiLock、SimpleNamespace 或另一个带资格外观的对象充当安装来源。新入口无路径、schema、validator、callback、accepted bool 或来源 factory 参数。

原 `_resolve_selection` 的规则体提为 `_resolve_selection_data`，只将 lock.metadata 与 lock.identity 替为两个显式参数。原 catalog/provider/selection 校验、host/engine、required/requires/conflicts、owner、pointer、source/support-source、profile/resource 闭合及摘要表达式与顺序保持。lock_identity 的原 `_hex` 检查仍在原 source/resource 检查之后。private 数据计算不检查外部 proof；新公开入口随后保留原 provided-proof hex 与 accepted-state 精确匹配检查。

旧 private `_resolve_selection` 保留薄数据桥供 `acceptance_context_identity` 使用；旧公开 `validate_selection` 的签名不变，映射稳定 lock.metadata/.identity 到新公开入口。不创建假 PiLock。accepted 的 context helper 仍可无 proof 计算上下文，不能改为调用要求 accepted proof 的公开入口。

兼容范围是原 PiLock 及现有 fixture 的稳定解析数据。自定义动态 property/getter 的读取次数、异常发生时序或并发变更不是本包承诺；不为此引入 callback 或反向来源对象。原 metadata fixture 无 identity、schema_version 等完整 formal 字段仍须成功；metadata 含与独立 lock_identity 不同的 identity 也不得新增拒绝。新入口不自动调用 header 或新增 full schema/root exactset/type/cap gate。

所有原输出字段、tuple 顺序、digest/canonical/projection、deepcopy 选定 provider 与原错误类别保留。不改接受集合、source_identity/Node/build 规则，也不重新设计畸形数据异常治理。可计算上下文与 caller supplied proof 不认证 issuer、来源或验收授权。

明确批准 `_version` 的唯一 lazy import 从 `pi_dependencies.VERSION` 改为已接受的 `pi_lock_resolution.VERSION`；使用同一原 regex 对象与原 isinstance/fullmatch 判断，不复制表达式或改成 eager import。不据此宣称整个 Python/controller 闭包已通过。

## 写入及验证范围

唯一 writer 只改 `src/agentcfg/pi_capabilities.py`，新增 `tests/test_pi_selection_data.py`。旧测试、schema、source/helper、runtime 声明、部署、guard、docs 与状态由本包禁止修改；root 单独写设计与记录。前提不符、事务/锁/来源问题、超范围或两种有效修复仍失败升级 root。

新测试保存本轮前整个 caps 文件与独立原 resolver/公开 proof 检查基线；原基线不能经新入口或新私有桥。以真实合法最小 fixture、正式 v2 Base/Full 数据及 current/candidate/accepted、support source 和既有 Node/build 合法控制比较原基线、旧 wrapper 与新入口十字段及 context/runtime 身份。正式 v1 本来没有合法 Base/Full selection，沿用既有 read_lock 测试保持其兼容，并核新数据入口与旧 resolver 同样拒绝；不为新接口扩展 v1 选择范围。metadata 缺 identity 与不同 identity、accepted 无 proof 的 context helper、缺失/过期/坏 hex proof、current/candidate supplied 合法任意 proof、身份/host/engine/source/resource 变化均保留原结果。负例不能用恒拒绝代替合法对照。

input 不变、返回 frozen、相同 regex 和调用时不为了 `_version` 导入 backend 需要直接观察。IO/环境/进程哨兵仅覆盖实际数据调用，不称 cold interpreter 或 installed 资格。已有原规则套件复用，不新增镜像实现的全量规则测试。

精确默认命令（原临时 HOME、禁网络、假子进程及无第三方宿主 guard）：

```text
/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python -B -m pytest -q -rs tests/test_pi_selection_data.py tests/test_pi_provider_bindings.py tests/test_pi_capability_manifest.py tests/test_pi_dependencies.py tests/test_pi_lock_header.py tests/test_pi_lock_resolution.py tests/test_pi_lock_families.py tests/test_pi_lock_layout.py
```

原 owner namespace 受限环境若仍触发已知 guard，保留失败并使用此前已授权的 normal-owner 离线边界；不放宽 guard，不运行 SDK/native/真实账号。修复后只重跑受影响范围。稳定 diff 才交独立审查，root 最终验收代码、旧基线及实际结果，各轮不累加。

## 后续资格

actual installed producer 必须先验证完整正式 metadata，并独立绑定真实 source/receipt/inventory、原角色、physical instance/current、issuer、私有 grant/channel/activation 及持续 source hold。该 producer、严格资源读取、完整声明/依赖/ABI、controller 与原生均未由本包实现。正式 7/100、全部产品 gate、strict metering 前 AUTO OFF 与 Recovery3 待单独授权保持。

2026-10-07 稳定默认验收：两文件实现，独立旧 resolver/context/public proof 文本 5256B 与前像逐字相等；same VERSION retarget 单独验证。指定八套一次 365 passed、2 个旧 v1 状态不适用 skipped（52.89s，42 个新用例无跳过），root 全增量及独立 executor gpt-6.1-sol/medium 稳定复核 0P1/P2；30 输入 receipt `9d7002984b608160eea831169a247613048d22c7d43c0eb6631a8f045c020f49` 已接受。归档保留实施时原设计文字和 root 批准的 v1 范围，本文随后修正文档；未改代码或重复测试。数据、安装来源与产品资格继续分别记录。
