# ReadSeek 视觉资产、缓存与 T086 代码收尾

2026-09-18。T086 标记仅表示普通插件迁入、监督与权限代码及 mock 工作完成，
不表示原生宿主、图像推理、平台验收或发布批准。

## 完整默认回归

```sh
.venv/bin/python scripts/verify-pi.py --tier mock --case all \
  --output /tmp/agentcfg-pi-mock-20260918-readseek-vision.json
```

- 开始：2026-09-18 08:33:07 UTC。
- 结束：2026-09-18 08:39:21 UTC。
- pytest：1406 passed，7 subtests passed，退出 0。
- Node：216 passed，0 failed，退出 0。
- 执行期间没有修改本次 Python/TypeScript/MJS/JSON 源文件。
- 后续 bootstrap/managed 活动期间的只读可用性查询及准入后复核修改，由 20 项 Node 定向回归覆盖。
- 统一 mock 使用 Python 3.11.11、Node v24.1.0；定向 Node 使用 v24.14.0。
  二者都不作为第三方宿主或模型的原生证明。

## 实际模型数据核验

固定 Qwen3-VL GGUF 修订：`52d6c8ffea26cc873ac5ad116f8631268d7eb503`。
数据保存于 `/tmp/agentcfg-readseek-model-data-44i3_3y0`；真实下载器和安装器核验通过：

| 文件 | 大小（字节） | SHA-256 |
|---|---:|---|
| Qwen3VL-2B-Instruct-Q4_K_M.gguf | 1,107,409,952 | `089d75c52f4b7ffc56ba998ffc50aae89fcafc755f9e7208aacca281dca6c2ae` |
| mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf | 445,053,216 | `f9a68fabba69c3b81e153367b2c7521030b0fa8bb0de400c9599c8e6725f9c82` |

固定修订的模型元数据声明 Apache-2.0，许可文本和来源保存在
`agents/pi/build/licenses/readseek-vision/`。没有执行权重或运行推理。

## 26 来源中间锁与四配方安装

源码副本：`/tmp/agentcfg-pi-lock-probe-8hwkbi6f`。
锁 identity：`d578b5a58e45f4ce9f32075fad143d8bae09f7367c97d0120fdf2afeffe2d9b9`。
它早于随后加入的视觉依赖闭包加强检查及 bootstrap 查询修订，不是最终候选。

四配方均从该锁完成 npm ci --ignore-scripts、原生文件投影、两份视觉数据安装、校验和密封：

| 配方 | 临时实例目录 | 安装状态 |
|---|---|---|
| pi-default | `/tmp/agentcfg-pi-vision-install-h3q60gj3` | installed |
| pi-managed | `/tmp/agentcfg-pi-vision-install-ie69sfhg` | installed |
| pi-codex | `/tmp/agentcfg-pi-vision-install-cg6t37rw` | installed |
| pi-cursor | `/tmp/agentcfg-pi-vision-install-0qxrgjv_` | installed |

模型数据使用本轮从固定 URL 下载的已验证数据缓存，每次安装重新流式核验。
没有复制其他实例的运行包；这些检查也不作为 cold-rebuild 或原生验收证据。
四次安装均 `host and model execution: not-run`。

## 尚未完成

macOS x86_64 原生来源构建、最终调用方/来源清单、web 适配、最终锁和 native/live 验收
仍由后续任务跟踪；其他三个平台继续未验证。
