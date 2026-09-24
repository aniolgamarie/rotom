# vendor 资产交付方式

更新日期：2026-09-24，当前锁 `9d6a927093f066c9428a5c193a636c4d73c5e64c946d24dc6a08185cf3f0dbf0`。下方早期验证记录保留其原候选语义。

## 背景

六个 linux/all 外部资产（约 1.68GB）放在 `locks/pi/vendor/`，使 sync 可使用已校验的本地输入。这六个 Codex 发行物和 GGUF 模型文件**不进入 Git**，由固定 URL 或离线制品提供；`locks/pi/manifest.json`、四配方 npm 锁和当前锁引用的本地/git 源码 vendor 包则进入版本库。

另一台机器取得仓库后，先运行下述获取脚本或导入六个离线资产，再按使用指南执行 agentcfg validate、sync 和 apply。sync 消费并校验现有锁，无需重新生成锁。缺失资产时 `read_lock` 与 sync 会明确失败，不回退未锁定来源。已有历史候选的冗余 vendor 包仅保留在原机器，不作为当前候选的必需交付物。

六个资产（固定 URL、大小与 SHA-256 全部来自 `agents/pi/dependencies.json`）：

| 资产 | 大小 | 来源 |
|---|---:|---|
| codex-bwrap-linux-x86_64 | 261,611 B | github.com/openai/codex releases |
| codex-responses-api-proxy-linux-x86_64 | 4,548,550 B | 同上 |
| codex-code-mode-host-linux-x86_64 | 25,729,904 B | 同上 |
| codex-linux-x86_64 | 98,981,886 B | 同上 |
| readseek-vision-projector | 445,053,216 B | huggingface.co Qwen3-VL-2B GGUF |
| readseek-vision-model | 1,107,409,952 B | 同上 |

darwin/arm64 资产未 vendored，保持固定 URL 下载模式（本轮平台不需要）。

## 获取方式（任选其一，校验相同）

### A. 固定来源重建（推荐，有外网时）

```sh
.venv/bin/python -B scripts/fetch-pi-assets.py
# 只补单个：--only readseek-vision-model；重下损坏文件：--force
```

脚本行为：读 `agents/pi/dependencies.json` 的固定 URL → 下载（断点续传、每轮全量 SHA-256/大小校验、截断或损坏自动整体重下，至多 8 轮）→ 临时文件 `0600` 原子发布到 `locks/pi/<vendor_path>`。已存在且摘要一致则跳过；摘要不一致的已存在文件默认拒绝覆盖（`--force` 或人工核对后重下）。URL 校验拒绝非 https、内嵌凭据或带 query/fragment 的地址；错误信息不落签名参数。

### B. 制品镜像 / 离线拷贝

由构建机把六个文件按 `locks/pi/<vendor_path>` 相对路径拷贝/打包到目标机同路径（scp、制品库、U 盘均可）。锁对内容的校验与来源无关——`read_lock` 与 sync 只做 SHA-256/大小校验。放好后跑一遍方式 A 的脚本（全部显示 `verified` 即证明输入完整）或直接进入 sync。

## 干净环境验证记录

- 2026-09-21 v1：复制完整冷源集到全新目录（`copy_source`），vendor 随拷贝到达，fetch 脚本对六个资产全部输出 `verified`（mirror 路径 + 摘要校验生效）；随后以改动后的源码校验旧 manifest 被正确判 `pi-lock-missing-or-stale`（锁过期检测生效）。
- 2026-09-21 v2：删除 vendor 后由固定 URL 实际下载重建（github 资产直连成功；huggingface 资产视出口连通性），随后 `read_lock` 完整校验通过。结果见 [实施记录](../../specs/001-unify-pi-capabilities/implementation-progress.md)。

## 许可与来源

许可文件不在 vendor 目录内：各资产的 LICENSE/NOTICE/SOURCE.json 随运行包安装时从 `agents/pi/build/licenses/` 收录（`install_assets` 每次校验存在性）。资产 URL、提交与摘要的登记来源是 `agents/pi/dependencies.json` 与锁 manifest，二者一致才可通过校验。
