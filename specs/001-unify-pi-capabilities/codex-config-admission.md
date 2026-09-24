# Codex 0.154.0 配置准入补充评估

评估日期：2026-09-17；决定日期：2026-09-18。用户已选择方案 A：保留官方 CLI，对无法核验的系统／企业配置拒绝执行。方案 B 不实施。尚未执行真实 Codex。

## 已确认的限制

本轮依据固定 `rust-v0.154.0` 源码复核：

- `exec --ignore-user-config --ignore-rules` 不关闭系统配置、受管配置和云端配置。`exec` 的 LoaderOverrides 没有整体关闭这些来源的 CLI 接口。
- 系统配置和云端片段参与配置层合并；legacy managed 配置还可能在 CLI overrides 后应用。设置空 `mcp_servers` 表不能删除较早层中的服务，因为表按键递归合并。
- 某些组织账号会加载云端配置，后台还会刷新共享配置包。事先读取一个文件或另起 `app-server config/read`，不能证明随后 `exec` 进程最终使用了同一份配置。
- 官方 CLI 当前没有“在同一进程中解析最终配置、由 agentcfg 验证、再初始化 MCP/hooks/工具”的准入接口。

来源：

- [exec 初始化](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/exec/src/lib.rs)
- [配置加载顺序](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/config/src/loader/mod.rs)
- [CLI overrides](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/config/src/overrides.rs)
- [云配置服务](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/cloud-config/src/service.rs)

## 可实施的两种边界

### A. 保留官方 CLI，对无法证明配置来源的环境拒绝执行（已选择）

维持原定官方 CLI 和原生工具路线。只允许明确满足受限配置条件的部署；系统/MDM/云配置无法排除或无法核验时，在启动 Codex 前失败。检查必须覆盖所有实际配置来源，不能仅检查 `/etc/codex` 或读取一个 plist。

这需要把稳定、受信的机器管理配置作为运行前提；独立预检无法给出针对管理员并发修改的原子证明。组织账号和受管机器仍在迁移范围内，标记为受限制或未通过，不能宣称任意账号/机器完整可用。不会恢复 codex-delegate，也不会切回 MCP 工具桥。

### B. 维护最小 Codex 分支，增加同进程配置准入（未选择）

在最终配置解析后、插件/MCP/hooks 初始化前增加 agentcfg 准入协议，绑定配置身份与冻结授权，并限制后续刷新对该次运行的影响。保留 Codex 原生工具；补丁、构建工具链、四平台二进制和升级回归进入依赖锁与许可证记录。

此方案增加长期维护和发布工作，改变“使用官方发布的 CLI 二进制”这一既定选择。不能在未选择前悄悄实施。

## 不依赖选择的已修复项

CLI override 的键按点号拆分，不理解带引号的 TOML 动态键。`projects` 现在通过整个 inline table 传值，保留含点号、引号、等号和非 BMP 字符的目录名。该修复仅解决参数编码，不解决上述配置层准入。

## 已实现的受限准入

- 固定 `/etc/codex` 必须不存在或为空；配置、规则、技能、空文件、坏链接以及未识别条目均会拒绝，文件正文不读取。目录权限／身份无法核验也拒绝。
- macOS 用 CoreFoundation 的 `CFPreferencesCopyAppValue` 检查与官方 CLI 相同的域和两个键。只判断存在性，不读 plist 替代、不解码或输出受管内容。API 不可用或返回不能判定的结果时拒绝。
- 启动时仅从所选实例 `auth.json` 分类账号，文件必须为私人单链接文件；不读取全局账号。明确 API key 模式、已知个人 OAuth plan 可准入；组织、未知、混合或其他尚未适配的身份拒绝。JWT 分类不是认证证明，认证仍由 CLI 完成。
- 父监督者在创建 worker 前检查，worker 在创建 Codex 子进程前再次检查，并重新验证授权。每次 start/resume 均走该路径。
- `official-cli-restricted-v1` 纳入 `execution_policy_digest`；报告仅记录策略 ID、账号类别与非原子边界，绑定当前 run/request，不保存令牌或配置正文。
- 登录先检查系统来源；由于 login 没有 exec 的忽略用户配置选项，实例存在 `config.toml` 时拒绝登录，不自动修改或删除该文件。
- 默认 doctor 只展示支持条件，不读取账号、不执行 CoreFoundation 查询，也不把配置准入等同于登录或模型通过。CLI／工具桥仅公开固定原因码。

管理员配置、账号归属和类型在运行期间保持稳定是本路线的运行前提。启动前重复检查缩短观察间隔，但不构成原子配置绑定；后续账号刷新或管理员并发修改也不在此保证内。

## 验证状态

已完成临时系统目录、虚构令牌、假 CoreFoundation 与假 CLI 的隔离测试。真实系统配置、macOS 偏好查询、官方 CLI 项目配置解析、沙箱和模型调用仍待独立原生／实网验收。组织账号等兼容性缺口保留，不能表述为任意账号均支持。
