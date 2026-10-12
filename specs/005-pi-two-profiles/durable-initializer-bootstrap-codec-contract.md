# Initializer 私有 bootstrap 的纯编码契约

2026-10-09 Root。接续 durable-initializer-principal.md 的匿名 carrier 路线，冻结 Python producer / Node receiver 共用数据；只纯 codec，无 carrier IO/角色发行/认证/launcher/SDK factory，不把 DTO 或随机格式当 principal。原 Durable 九消息、Node 五消息与新 bootstrap 各自分开。

## 逐字段封闭协议

单 frame = 4-byte big-endian payload长度 + canonical ASCII JSON，payload <=2048B，完整frame<=2052B；恰好一帧，零尾数据。恰好以下12字段：

| 字段 | exact 值/类型 |
|---|---|
| schema_version | int 1，bool/float 拒绝 |
| role | string durable-initializer |
| instance_id | lowercase hex64 |
| supervisor_activation_id | lowercase hex32 |
| manager_activation_id | lowercase hex32 |
| host_lease_id | lowercase hex32 |
| grant_generation | exact int 0..9007199254740991，两语言安全整数交集 |
| runtime_identity | lowercase hex64 |
| lock_identity | lowercase hex64 |
| slice_identity | lowercase hex64 |
| adapter_identity | lowercase hex64，仅自有初始化adapter固定公开来源身份，非secret/hash-of-secret |
| role_token | lowercase hex64 的私密token；不得进入日志/摘要/文件/env/argv/普通diagnostics |

canonical要求字典key按ASCII lexical排序、无空白、原值无转义需要、JSON标准decimal整数，UTF8/ASCII原字节比canonical重新编码完全一致。拒绝BOM/重复键/未知或缺字段、额外frame、非finite/float/exponent/-0/前导0、surrogate/非ASCII/数组或嵌套值；在payload分配/解码前先核4BE长度与完整frame大小。12字段均为固定小标量，Root最大合法payload已测并写fixture相关报告，不接受任意2048字段填充。

## API 和秘密边界

Python src/agentcfg/pi_initializer_bootstrap.py:
capture_initializer_bootstrap(value) 只exact dict及exact scalar，返回自有 frozen slots InitializerBootstrap；repr/str始终redacted，不把token或其hash作为身份输出。encode_initializer_bootstrap_frame(value) 只exact自有类型且逐字段重新核；decode_initializer_bootstrap_frame(frame) 只exact bytes按上述cap/canonical解析并capture。公开DTO构造/copy/有效frame仍是数据，不认证、不提供初始化或IO资格。坏参数绑定也输出固定 PI_INITIALIZER_BOOTSTRAP_INVALID、exit4，清掉foreign exception cause/context；不回显keyword/值/frame。只有合法显式encode返回原私密frame。

Node agents/pi/runtime/initializer-bootstrap.ts:
captureInitializerBootstrap(value), encodeInitializerBootstrapFrame(value), decodeInitializerBootstrapFrame(frame)。同一frame、同一12字段、同一界限。capture拒绝proxy/访问器/symbol/foreign prototype，不执行foreign getter；只plain或null-prototype原数据属性。自有opaque冻结object/私有WeakMap保存字段，默认JSON/inspect/string不列token；重建/copy/structuredClone不成为原codec对象，constructor不接受公开恢复。decode只原Buffer/Uint8Array、非proxy/共享内存/异常view，先cap再copy，输出固定Error code/exitCode4且无raw foreign cause。encode仅原registered codec object而仍非authority。不要新增package依赖、SDK import、private host API/monkeypatch。

Root固定 tests/fixtures/pi/initializer-bootstrap-v1.json 为synthetic golden：full input、canonical payload、frame_hex/长度。两语言分别精确比对同一golden bytes；另最小/最大generation、字段mutations、每cap边界、duplicate/unknown/trailing/noncanonical、array/proxy/getter/aliascopy、源mutation后capture不变、token在合法encode里存在而repr/errors/JSON无token，坏参数fixed errors。测试不能仅镜像实现；有效RED需正常编码/roundtrip/封闭失败行为都被破坏后观察断言，不把缺文件collectionfailure算行为证据。

## Writer / 验收 / 升级

executor唯一可写两个新source、tests/test_pi_initializer_bootstrap.py、agents/pi/runtime/tests/initializer-bootstrap.test.ts；fixture和contract由Root唯一写，不改它们。证据 durable-initializer-bootstrap-codec-implementation-review01。你不是唯一作者，不回退他人编辑。固定pytest仅新模块；Node使用既有默认脚本 /home/weixiaoxian.wxx/.nvm/versions/node/v24.14.0/bin/node scripts/test-pi-mock.mjs agents/pi/runtime/tests/initializer-bootstrap.test.ts，私有/data TMPDIR使默认mock bwrap与网络/子进程guard保持。只仓库自有纯codec，不加载第三方宿主/SDK，fixture无真实token，临时HOME。保存真实起止/exit JSON和RED/GREEN日志，稳定diff/pins/report后STOP。跨语言编号/cap/secret边界推翻或同失败两有效修复升级Root；不改conftest/mock guard/state/tasks/docs/OMP/其它runtime/native material，不再派生。只默认纯codec，正式8/100、AUTO OFF、全部来源/角色交付/真实验证待完成。

## Root 参数与属性裁定

Python固定错误覆盖三codec函数和自有InitializerBootstrap公开构造器的参数绑定；合法DTO构造/copy保留，不能改dataclass或上游实现，可在自有声明用装饰/明确constructor组织。Node12个原自有data descriptor必须enumerable；nonenumerable也固定拒绝，getter/symbol/proxy仍零foreign回调。验收加入未知keyword sentinel/nochain与nonenumerable反例。
