# Durable lock header 与固定 schema 资源

2026-10-07，root 选择 header/resource proposal review01 的有限三文件实现。此包只复用原 schema、版本和 identity 检查；不是完整 metadata/installed validator、来源或能力生产者。此前 resolution 默认验收保持，正式 7/100、产品 gate、AUTO OFF 与 Recovery3 授权边界不变。

## 固定接口与顺序

新增自有 `pi_lock_header.py`，唯一公开接口 `validate_lock_header(manifest, *, schema_version) -> None`。输入是已解析标准 JSON 数据，预期版本须 native int 1 或 2。函数明确包含固定自有 schema 资源 IO，不称 pure；不接收 caller schema/path/validator、callback、accepted flag、PiLock/Workspace 或 source factory。None 只表示完整 manifest 满足这三组原规则，不表示 bindings 语义、recipe、文件、安装、角色或授权通过。

调用时从新模块自身 `Path(__file__).resolve().parents[2] / "schemas/pi-lock.schema.json"` 读原正式 schema；无 caller 路径、cwd/PATH/site 扫描或 fallback，无 import/constructor 时读取、无 schema/validator 缓存。保留原 `json.loads(path.read_text())` 资源语义和原 `Draft202012Validator(schema, registry=Registry()).is_valid`，包括完整 v2 bindings 结构及所有 schema 条件。此兼容包不新增 caps/stat/owner/link/duplicate/UTF8 收紧；实际 installed 的严格资源来源读取、完整 seal 和实际 Python/包资源资格另冻，不能用此 loader 代替。

在 `read_lock` 原 schema 位置 lazy 调用 header，仍先读/解析 schema，再核 manifest 版本，再核 schema，再用原 `deployment.json_bytes` 与 SHA256 核去 identity 的完整投影。不复制或改变 canonical helper；其 PyYAML eager 导入须计入完整闭包。identity 坏不调用 recipe；header 成功后原 recipe 检查独立执行；recipe 成功才到原位置 v2 `validate_manifest_bindings`。后续 accepted/profile/source/archive/build/asset/platform/runtime_files/raw pair/resolution/license/selection 检查及原最终 ConfigError 均保持。新函数不修改输入；VERSION 与已经接受的 resolution 代码不改。

固定失败是 `ValueError("pi-lock-header")`。所有内部普通 Exception 仅转换为新的固定错误，显式清其 cause/context 后 bare re-raise，包含 caller 正在处理另一个异常的情况；不能只 from None，不能附文件/正文/秘密或改 caller 原异常，BaseException 透传。旧 `read_lock` 的错误边界不在此包另行升级。

repo 布局为 `/repo/src/agentcfg/pi_lock_header.py` 到 `/repo/schemas/pi-lock.schema.json`；未来 Full 为 `/runtime/supervisor/src/agentcfg/pi_lock_header.py` 到 `/runtime/supervisor/schemas/pi-lock.schema.json`。后者只确定布局，不代表声明或安装已可用。原 `pi_dependencies.ROOT` 和已有顶层 validator 兼容符号暂保留，但不让 ROOT 控制新 schema 路径。Base constructor/cold 路径不导入 header 或发现 Full 可选资源；Base 的原 `read_lock` 必需 schema/公共共享代码读取不冒充新增 Full 可选访问。

## 写入和验收

唯一 executor 只写新 `src/agentcfg/pi_lock_header.py`、`src/agentcfg/pi_dependencies.py` 的上述接线、新 `tests/test_pi_lock_header.py`。不改其他源码、原测试、schema、locks、runtime_files/installer、roles、guard、docs/state 或上游。前提改变、需扩范围、来源/事务/锁不明确交 root。

保存实施前完整 `read_lock` 和 schema 字节，独立旧基线不得调用新 header。真实既有合成 v1/v2 Base/Full/global current/candidate/accepted fixture 对照 identity/full metadata/raw pair/binding/runtime identity；schema/unknown/reserved现代字段/native version/identity 与固定资源缺失/坏 JSON/读取异常成对正负控制；真实调用记录证明 schema→version/schema→identity→recipe→binding 短路顺序；导入/Base constructor 的 schema与 Full 可选读哨兵；每次调用固定路径且无 cache；ordinary/outer exception 固定无链与 BaseException 透传。只证明默认 fixture/数据兼容，不授 installed/source/issuer/DB 资格。

一次适当 offline pytest：新 header 包、已经接受 resolution 包及原 dependencies/families/capability_manifest/provider_bindings/lock_layout 六个相关文件；临时 HOME、断网、假进程、原 guard，不启动第三方宿主。UID 视图限制只记未验证，再使用批准的普通 owner 视图保持原检查。失败或修改后仅必要重跑，稳定 diff 再独立审查。共享新源码、正式 schema 资源与完整 Python/wheel 声明及原生资格仍是后续任务，不宣称可部署。
