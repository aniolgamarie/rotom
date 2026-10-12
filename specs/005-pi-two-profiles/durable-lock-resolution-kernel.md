# Durable lock resolution：首个共享校验内核

状态：root 已决定的有限实现包。仅提取原 `PiBackend._validate_resolution` 的数据规则，尚无默认测试、installed 来源或原生资格。依据 installed-origin API proposal review01，先关闭这一组可明确独立验收的规则；完整 metadata/schema/selection/collector API 仍待冻结。

## 接口与兼容要求

新增仓库自有 `src/agentcfg/pi_lock_resolution.py`，公开 `validate_lock_resolution(package, resolution, piece, manifest) -> None`。四个参数都是原调用已有的已解析数据；`piece` 内的 package_path 是锁中的逻辑相对路径，只用于词法路径计算。接口无 Tree/文件读取、进程、环境探测、schema 加载、回调、Workspace、PiLock 或来源工厂。None 仅表示这些数据符合原 resolution 规则，不证明文件来源、完整 manifest、许可、安装态、加载态、issuer 或能力。

保留原 221–297 行的全部规则、调用顺序及合法输入域：完整直接依赖和传递依赖图、祖先 node_modules/peer 查找、v2 locked AI 与 source 对应、归档相对引用、VERSION、无 credential 的 HTTPS、完整 sha512。不得缩成所选 SDK/AI 两包，不读取 archive 替代图校验。原 lockfileVersion 的数值相等、link/inBundle/optional 的 truthy 语义此次原样保留；新 origin 的 strict JSON、精确 integer 和资源 caps 另审，不在兼容提取中顺手修改。

新公开入口在正常返回之外，对原规则中的普通 Exception 统一在 except 作用域之外抛出新 `ValueError("pi-lock-resolution")`，不保留输入异常的 cause/context；不捕获 BaseException。内部完整规则可由私有函数承载。原私有 `_validate_resolution` 仅 lazy 委托此入口；`read_lock` 所有原仓库 schema、recipe、source/archive/build、license、digest、selected pair 与 selection 检查及最终 `pi-lock-missing-or-stale` 错误保持。纯函数不修改输入。

VERSION 的同一原 regex 放入新共享模块，`pi_dependencies.VERSION` 保留指向它的兼容导出；新模块禁止反向 import pi_dependencies。原 capabilities 的版本引用和所有 digest/canonical/metadata 输出保持。新模块仅原已有的自有 config/path helper 和标准库依赖；v2 `validate_locked_ai` 按原分支 lazy 引入。不得引入 Full origin/schema/wheel/role 或可选资源发现。

## 唯一写入与验收

executor 只写 `src/agentcfg/pi_dependencies.py`、新 `src/agentcfg/pi_lock_resolution.py`、新 `tests/test_pi_lock_resolution.py`。不改 capabilities、正式 schema、locks/runtime_files、installed origin/writer、guardian/current/lease、上游或其他既有测试。超出范围、前提改变、来源/事务/锁语义不明确，交回 root。

默认测试使用合成数据、仓库 fixture/临时 HOME、断网和假子进程，不启动第三方宿主。验收包含合法 v1/v2 与 npm/归档直接依赖、真正祖先传递/peer/AI 图的正例；图缺失、source mismatch、credential/link/坏 sha512/绝对或陌生归档的负例；输入不变、固定错误无秘密/cause/context；IO/process/env 哨兵；真实既有 fixture 的 raw pair、identity/metadata/validated_bindings 在仅本轮提取前后相等。不能使用两个都调用同一新入口的比较代替旧行为基线。

执行一次适当 pytest：新测试、`test_pi_dependencies.py`、`test_pi_lock_families.py`、`test_pi_capability_manifest.py`、`test_pi_provider_bindings.py`、`test_pi_lock_layout.py`。仅在失败或修改后重跑受影响测试；若环境限制按原 guard 报环境未验证，不改 guard。writer 保存初末 pins、本轮精确 diff、实际命令/完整 stdout/exit 和旧基线构造方法，待稳定 diff 独立审查。

完成后最多获得共享 resolution 数据规则和仓库兼容的默认验收。正式 7/100、全部实际 installed/native/产品门、严格计量前 AUTO OFF 与未回复的 Recovery3 授权边界保持。
