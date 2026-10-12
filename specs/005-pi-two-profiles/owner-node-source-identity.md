# Node 资产接入能力绑定身份：纯接口包

2026-10-07，root 在新格式和真实字节暂存已经接受后发现：`pi_capabilities.source_identity` 的独立闭合字段不含 `node_archive`，asset format 只含 raw/tar.gz。合法新 Node 声明仍会被拒绝。因此不能据新 schema/helper/stage 验证宣称全锁或 capability binding 已接通。

本包只改 `src/agentcfg/pi_capabilities.py` 和新增 `tests/test_pi_node_source_identity.py`。不改 assets/parser/schema/license、候选来源行、profile、catalog/provider、recipe、manifest 或 gate；不读真实 Node/归档、账号、运行宿主。正式 modern 目前仅声明 pi-base，不能伪称已有 Full selector。实际 Node source 应在哪些 profile 声明、支撑哪个 provider，另在声明包冻结；Node executable 不是独立 agent 插件或 Durable 授权。

## 冻结的实现

保留全部旧有效原生 npm/git/local/raw/tar.gz/built 资产的身份字节语义。旧 projection/validation body 不调整 format 枚举或通用字段 allowlist；新增独立 Node 分支，在原 body 之前完成。新边界先核 exact dict，再捕获一次 `tuple(dict.items(source))`，全体 key 为 exact str 后才独立重建和哈希。对外来 dict subclass、非原生 key 在 legacy body 之前固定拒绝；这些不是由 JSON/schema产生的合法来源。旧有效原生输入继续走原 body，不将某个未核验 metadata 字段加入通用 allowlist。

独立原快照含 `node_archive`，或 exact str format 等于 `node.tar.gz` 时，只走 Node 分支。调用已接受公开 `capture_node_asset(snapshot)`；所有十项（vendor_path 可选）完整闭合、canonical URL/member/target/license/platform/vendor 关联和六项 node_archive 约束由该接口负责。缺 Node metadata、错 kind／format、额外字段、外来 nested 类型等不能降级回通用分支；不调用 opener/install/select/toolchain/IO。NodeAssetReference 是该原函数新返回的独立 metadata，非授权。

Node 的新 projection **精确**为下列七项，digest 使用原 `activity.digest`，不得自行再建另一算法：

```text
kind = "asset"
archive_digest = selection.archive_sha256
archive_member = "node-" + selection.release + "-linux-x64/bin/node"
target = "bin/pi-node"
platform = selection.platform
format = "node.tar.gz"
node_archive = {
  schema, release, platform,
  archive_sha256, binary_sha256, license_sha256
}
```

六个 selection 字段均来自完整捕获后的原值，独立重建。URL、vendor path和机器位置不加入身份；它们在捕获时必须符合该 release/archive 的唯一派生规则。许可文件路径不是自由字段，原许可 bytes 的 hash进入 node_archive；不能通过改 license 路径避开同发行物校验。source 顶层仍没有 version，provider 的 source_version保持资产的 None；嵌套 release 明确进入身份，不用宿主命令取得版本。旧源 digest 不变，新 Node digest 包含全部选择快照；这只是非秘密关联身份，不能授权安装／运行／审批／开库。

新 prefix/type guard/Node helper 的拒绝使用自有 fresh `ConfigError("pi-provider-binding")`，实际 cause/context 为 None，不改全局 `_fail` 或旧异常行为。capture/digest 的依赖失败也在退出捕获作用域后映射；不保留或修改原异常、不在错误正文带数据。型别核验先于任何可能的外来 key hash/eq、str comparison、mapping get/items或repr；旧有效原生分支无额外source转换副作用。仅内部固定原函数调用，不接受 provider/config callback。

## 验证与稳定接受

先写最终相关 tests，在原可执行 `source_identity` 上保留确切 source/test pins 与真实 red 日志，再实施。本轮不存在模块导入错误不能冒充行为 red。最终固定命令为：

```text
/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python -m pytest -q tests/test_pi_node_source_identity.py tests/test_pi_capability_manifest.py tests/test_pi_node_asset.py tests/test_pi_profile_projection.py
```

仍使用原临时HOME／离线／假进程 guard，不导入SDK、不开真实socket/锁/进程、Node或模型。新测试核：完整canonical projection预期、optionalvendor省略同identity、binary和license hash分别变化必改identity、release与archive变化在其所有派生字段一致时必改identity；missing/错metadata与互相不对应的派生字段固定拒绝、错kind/format不能fallback；snapshot mutation后成功值不变、毒化keys/str/int/mapping类零hook调用和ambient exception的固定链。测试使用虚构合法 hashes和许可路径，不读真实原材料。

旧身份的正控制使用合法 npm/git/local/raw/tar.gz 与 built fixture，expected按旧projection算出固定值；不能先在修改后调用同一函数得到expectation。对 Node-specific允许项仅加到旧有效row时须拒绝（有原正例），未知字段保持失败。静态逆去新增prefix/helper/import后原源码应逐字复原；若必须改旧body先升级root，禁止顺手放宽旧guard。默认相关检查通过后不额外全仓重跑。writer完成并STOP后由root与不同executor审稳定diff／pins／实际日志，不加总历史counts。

此包通过仍缺真实source候选/profile/catalog/provider关联、完整sealed receipt、registered owner reference/授权、正式锁、版本／exec／owner原生资格；Full与自动审核gate保持关闭，不勾选整个T079或T090。
