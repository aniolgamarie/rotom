# OMP permission-control 构建来源

仅记录已核实的来源与身份；本文件不代表补丁或正式运行包已交付。

| 输入 | 固定来源 | 核实身份 |
|---|---|---|
| OMP 源码 | https://github.com/can1357/oh-my-pi/archive/62bc57be1b03ef0802a33cf7f5f530e534527531.tar.gz | commit `62bc57be1b03ef0802a33cf7f5f530e534527531`；archive SHA256 `edcc0f93a0ab0c0223d0651bba3624c55a32d25494a43b0257ea626be1dff97d` |
| 完整 Bun lock | `locks/omp/upstream/bun.lock`，与上述源内 `bun.lock` 相同 | SHA256 `eaf18ef55ef20a21991d66417054d44528ad7767df294e710a5c24c4ce2b5c87` |
| Bun 工具 | https://github.com/oven-sh/bun/releases/tag/bun-v1.4.0 的 `bun-linux-x64-baseline.zip` | archive SHA256 `184fb4595f0d401a217cf7c78c1bc430ba83314dab7a8b94805babbf7fa7097f`；解压 executable SHA256 `33d56b070be6a9e3da0ab013038b43d1645d0534ca811ecdba4472599117eb4b`；执行 `--version` 得到 `1.4.0` |
| Bun 校验清单 | https://github.com/oven-sh/bun/releases/download/bun-v1.4.0/SHASUMS256.txt | 下载的 archive 与官方清单逐字节 SHA256 一致 |
| Native leaf | https://registry.npmjs.org/@oh-my-pi%2fpi-natives-linux-x64/18.3.0 | archive SHA256 `7c36e9d75567ee6894d895b8011172955ad1937401d8a3263a632996724a1fb2`；与官方 registry 的 SHA512 integrity 一致；modern/baseline 的 `__piNativesV18_3_0` 精确 sentinel 均通过 |

源码 root package.json 要求 Bun >=1.4。若重新编译 native，需要源码指定的 Rust nightly-2026-08-12 与 Bazel 完整工具链；本次维护选择供应同版本官方 native leaf，由 `packages/natives/scripts/embed-native.ts` 嵌入，然后调用 `compileCodingAgent`。不得以其它版本或官方 standalone 的摘要代替 native 输入身份。

目标 ABI 为 `permission-control/v1`。当前候选 series 顺序是 `0001-host-bridge.patch`、`0002-installed-only-tiny.patch`。候选源码测试和早期构建不代替最终运行包交付，正式资产摘要只能来自源码稳定后的实际构建。

独立输入契约为 `schemas/omp-permission-build-inputs.schema.json`。完整工具、native 资产和离线依赖闭包全部校验后才能创建 `build-inputs.lock.json`；未闭合时缺少正式输入锁是明确失败状态，不能用空列表、占位 SHA 或未检查的本机缓存替代。

工具与依赖供应在隔离维护目录完成；默认测试、sync/apply/run 不获取缺失材料。此阶段没有启动 OMP CLI/TUI、native addon、worker 或模型，也没有修改日常 OMP 配置。

## 已供应的独立输入锁

`build-inputs.lock.json` 已记录实际字节。工具缓存只有 Bun 1.4.0；依赖缓存只有一个 gzip tar bundle，解包相对上游源码根目录。bundle 包含根及各 workspace 的 node_modules、两种 native .node，以及 `permission-control-inputs/native-leaf.json` 的原始公开来源元数据；不包含编译输出/receipt/官方 recipe identity。安装基于未修改的完整 bun.lock，以 `bun install --frozen-lockfile --ignore-scripts` 完成 414 包；没有执行安装脚本或 native addon。所有 bundle 内符号链接必须解析到源码工作树内，构建解包同样必须检查路径边界。

依赖 bundle SHA256 `46ab144e81134c00633752ad3a474a52605984e47bcf1ee565d462934ad6a8c5`，大小 `646784300` 字节。这只证明输入材料身份，不证明 patched bridge 集成或宿主可用。

- `pi_natives.linux-x64-baseline.node`：SHA256 `295d195248b4e23ef8fb298dcbe45aad33bbed83b218586cb1cbe66981337b52`，184467992 字节。
- `pi_natives.linux-x64-modern.node`：SHA256 `0d112175090d11f8255bca783e6e367993bcadc08522abe5dca262b2b9547a1c`，184286992 字节。

下载 native 时官方入口曾出现 TLS 失败，随后官方代理路径与 npmmirror 路径都成功；最终缓存字节按事先取得的官方 npm SHA512 验证，镜像不提供替代信任值。

## 单次审查与 tiny 的本地源码依据

以下路径均相对于上述锁定OMP源码；只读源码和依赖源码，没有运行真实模型或标题worker。

- `packages/coding-agent/src/config/model-registry.ts` 的 `find`、`isUsingOAuth`、`getApiKey`、`resolveModelHeaders` 提供配置模型与宿主认证边界。审批服务只发送一次标准Anthropic Messages或OpenAI Chat Completions请求；不使用原通用SDK内部的重试、认证后推理重发和provider fallback。
- `packages/coding-agent/src/tiny/models.ts` 固定 `lfm2.5-230m` 对应 `LiquidAI/LFM2.5-230M-ONNX`、q4。`tiny/worker.ts` 使用 `tiny-title-runtime/transformers-<version>`，模型缓存根由 `packages/utils/src/dirs.ts:getTinyModelsCacheDir` 得到。compiled版本由既有 `scripts/compile-binary.ts` 固定 `PI_TINY_TRANSFORMERS_VERSION`。
- `subprocess/worker-runtime.ts` 的通用loader会调用安装、CUDA修复和写sharp stub，不能直接复用。审批worker仅验证并复用已存在且内容固定的 `omp-sharp-stub.cjs`，调用纯 `installRuntimeModuleResolver`，不调用任何安装/写入函数。
- 锁定依赖的transformers 4.3.0 `src/utils/hub.js` 使用 `<repo>/<filename>` 缓存键，`src/models/session.js` 与 `src/utils/model-loader.js` 解析q4模型和external-data；审批loader使用绝对本地模型目录、`local_files_only=true`、`allowRemoteModels=false`、禁用缓存写入和全局fetch。资源初检不冒充完整性证明：只有独立worker成功加载整个pipeline后才发送ready并允许一次生成，缺少external-data或原生依赖仍返回不可用。
- 真实安装、CPU加载时间、平台兼容性和模型质量仍须独立授权验证。首版仅把Linux x64列为候选，超出剩余5秒预算不会延长等待或下载修复。
