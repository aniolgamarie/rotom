# 现代运行包的许可证分发与来源准入

本文件记录 T006/T009 的实施决定。它约束当前 Linux x86_64 候选，不构成法律充分性意见、原生运行验收或正式锁发布。

## 所有权与交付

现代运行包将补充正文和来源记录复制到自有 `licenses/pi-modern/`，不向 npm 包目录添加或改写 LICENSE。历史 `license_sources` 仍作为候选来源身份记录保留；现代 npm 安装不执行旧 overlay，local/git 包仍检查原归档的许可文件。旧 profile 的安装行为不在本次变更范围。

这些文件使用现有 `runtime_files` 的显式选择、输入/输出 SHA-256、私有文件模式和收据 inventory 机制。只增加严格对应 `agents/pi/build/licenses/pi-modern/<文件名>` → `licenses/pi-modern/<文件名>` 的 `copy` 声明，不自动扫描收集文件。验证所选闭包时也覆盖这个自有目录。每个现代 slice 必须恰有一个选定的 `REGISTRY.json` 或 `REGISTRY-<后缀>.json`，其余来源/正文引用必须属于同一锁定目录。

## 完整注册表清单

清单使用 schema 1，顶层仅含 `schema_version`、`platform` 和 `packages`。当前平台为 `linux-x86_64`；其他平台须补充独立来源及运行证据，不能借用当前清单。`packages` 按锁内相对路径排序并覆盖完整的外部 HTTPS registry 图，包含嵌套、别名和 optional 条目。仓库自有 file 归档不进入 registry 图，其原许可检查保留。

每行的闭合字段为：`path`、`name`、`version`、`resolved`、`integrity`、`optional`、`os`、`cpu`、`libc`、`package_json_sha256`、`declared_license`、`status`、`archive_files`、`supplemental_files`、`evidence_files`。前九项与原完整锁一致，缺省 optional 为 false，缺省约束为 null。原生 bool/int 必须准确，路径规范化且限制在合法 `node_modules` 包路径；未知字段、重复 JSON 键、重复记录和重复文件引用拒绝。来源 URL 和 SRI 沿用完整锁的精确身份，不用包名与版本近似匹配。

三个文件引用列表均由 `{path, sha256}` 组成。`archive_files` 的 path 相对该包根，正文保留在原包；另两类 path 位于锁定的自有许可目录。每个引用必须有对应字节、散列和来源选择。正文位置与用途有以下状态约束：

- `archive-body`：必须有原归档正文引用，没有 supplemental；锁定 package.json 的字节及发布的 license 声明必须一致。完整 MIT 正文在 `data-uri-to-buffer` 的 README 中，使用明确引用和 SHA，而非将任意 README 当许可证。
- `fixed-source-body`：必须有 supplemental 和 evidence 引用；已固定 Pi / esbuild 发布身份及相应上游 commit 的正文。
- `declared-license-with-canonical-supplement`：必须有 supplemental 和 evidence 引用；目前仅用于已声明 Apache-2.0 的三个 AWS 包，保留“标准正文不等于 AWS 特定版权/NOTICE/确切源码 commit”的限制。
- `body-scope-unresolved`：无正文，有来源证据；候选可保存，正式启用必须拒绝。当前为 `proxy-agent-negotiate@1.1.0` 和 `standardwebhooks@1.1.1`，不代入其他范围的许可证。
- `optional-platform-excluded`：只允许完整锁明确 optional 且 OS/CPU 约束可证明不适用于当前 Linux x86_64 的条目；清单不冒称已取得其原包正文。package.json 散列及 license 声明为空，正文和来源引用为空。可选但适用于当前平台的缺包不能使用此状态，已安装排除包也拒绝。

非排除行必须有精确的 package.json SHA-256 与非空发布许可声明。完整图和文件的任何变化都要求重新形成清单，不能只沿用已知 15 行并遗漏新包。来源状态是工程准入事实，不推断法律充分性。

## 检查顺序

读取现代锁时，所选 slice 先验证现有 runtime 文件来源，再核对清单与完整 registry 图、正文/证据引用。candidate 允许明确未解决行；current/accepted 必须无未解决行。构建新的 candidate 在写发布目录前执行相同检查。`runtime_identity` 在写入 guard 之前重新检查实际清单，不能依赖可伪造的内存 PiLock 或已缓存绑定。

安装现代入口先以既有原语复制全部已核对的仓库文件，再检查清单涉及的实际包身份、package.json、原归档正文和自有补充正文。此处要求来源已准入；不能写运行描述/收据并报告成功后再发现未解决许可证。运行包 seal/status 通过 installed 验证复核相同条件，收据覆盖自有正文和来源文件。该机制不新建激活事务、下载器或另一份依赖锁。

## 默认验证范围

使用临时 HOME、网络阻断和假安装器。必须覆盖完整图缺行/多行/版本或 SRI 变化、正文/证据缺失或篡改、未知字段/重复键/布尔误用/路径越界、candidate 与 active 的未解决来源差别、optional 平台排除边界、修改内存 PiLock 的绕过、现代 npm 目录不增加 LICENSE、运行收据确实包含自有正文，以及其缺失/漂移导致 status damaged。保留 legacy 回归。实际 Base 候选只进行静态锁/文件读取，不启动 npm、SDK、CLI、模型或账号。其 sources 未准入时保持未启用。
