# Linux 独立 helper 构建边界

本文件属于 T009 的运行包来源准备。现代 Base/Full 的宿主 PID 命名空间入口固定为运行包内 `bin/pi-bwrap`，旧 Codex 委派仍使用自己的发行物。独立 helper 尚未进入正式锁或激活流程；缺失时拒绝，不回退到 Codex、PATH 或系统安装。

## 固定输入

| 输入 | SHA-256 | 原始来源 |
|---|---|---|
| bubblewrap 0.13.0 源码 | `4734237473c0e5d695e4e9034a34e43b2dbf5164655bd13fa59ae376b2b7a765` | [上游发行物](https://github.com/containers/bubblewrap/releases/tag/v0.13.0) |
| libcap 2.77 源码 | `897bc18b44afc26c70e78cead3dbb31e154acc24bee085a5a09079a88dbf6f52` | [kernel.org 发行目录](https://www.kernel.org/pub/linux/libs/security/linux-privs/libcap2/) |
| Meson 1.9.0 wheel | `45e51ddc41e37d961582d06e78c48e0f9039011587f3495c4d6b0781dad92357` | [PyPI 版本页](https://pypi.org/project/meson/1.9.0/) |

三份归档经校验后已从候选缓存导入工作区的 `locks/pi-modern/build-inputs/<sha256>/<name>`，尚未生成选择它们的正式 Base manifest。bubblewrap 摘要比对发行说明，libcap 比对通过 HTTPS 获取的 `sha256sums.asc` 文本，Meson 比对 PyPI JSON 元数据；没有执行 libcap 的 PGP 签名验证，不把文本摘要核对描述为签名验证。

`pi_bwrap_source.py` 在读取 tar 条目前先校验固定摘要，限制 XZ 内存、总展开大小、文件数量和普通文件总字节。仅接受唯一版本根及两个精确的许可别名 `COPYING.LIB`/`LICENSE → COPYING`；准备时将别名物化为相同字节的普通文件，不提取任意链接。根目录和 `tests/use-as-subproject/` 的两个 `meson.build` 保持各自相对路径。初次人工缓存曾按 basename 覆盖根文件，已按完整成员路径纠正，真实源归档未改变。

## 构建与产物合同

构建入口使用原样上游 Meson/Make 规则；本仓库只负责固定输入、安全准备、构建环境和产物记录。libcap 静态链接进入 helper，bubblewrap 使用公开选项关闭 SELinux、man、completion 和上游测试构建；不修改上游源码，也不执行构建出的 helper。编译器自身的配置探测及 libcap `_makenames` 属于构建步骤，不计作 helper 的行为验收。

构建在独立网络命名空间中进行，只读挂载系统编译工具和动态加载器缓存，唯一可写工作目录为新的私人临时目录。环境固定为临时 HOME/TMPDIR、系统工具 PATH 和确定性构建变量；没有用户账号目录、实例目录或整个仓库挂载。缺少 bwrap、工具或 namespace 能力时失败，不转为直接在宿主执行构建。

产物须包含 helper、bubblewrap 与 libcap 许可证及来源/构建记录。记录区分原始输入归档摘要、构建脚本摘要、实际工具链、构建包装器、二进制摘要和最终产物归档摘要。源码 URL 只能说明输入来源，不能冒充本机编译归档的下载 URL。ELF 文件头和 `readelf` 的动态库/GLIBC 记录属于静态检查，不能代替执行证明。

`scripts/build-pi-bwrap.py` 已完成当前 Linux x86_64 的两次独立构建，候选状态为 `built-not-executed`。两次均观察到退出码0，二进制、完整产物归档和候选记录完全一致：

| 产物 | 字节数 | SHA-256 |
|---|---:|---|
| `bin/pi-bwrap` | 128368 | `c2ef9427eddbed90e2f52aa6cb3bf08ba514e456d520d19cfbe43af125d79997` |
| `pi-bwrap-linux-x86_64.tar.gz` | 64256 | `9672205cfff3f07f1fa9a81a2085a3fc617054c37df5a5cb9fce262a74325068` |

实际执行使用仓库主工作区的 Python 环境，在本特性工作区调用：

```sh
/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python -B scripts/build-pi-bwrap.py \
  --sources .cache/pi-two-profiles/candidates/bubblewrap-build-inputs \
  --output /tmp/pi-bubblewrap-build-20261004-run04
```

第二次仅将输出改为新的 `run05` 目录；已存在的输出目录即使为空也会拒绝覆盖。产物已另存私人候选缓存。自建资产 schema、离线导入和锁/安装校验接线已实现，实际 Base 依赖声明与完整运行包仍未完成，不提供尚未通过检查的产品启动命令。

静态动态库清单仅含 `libc.so.6`，观察到的最高 GLIBC symbol version 为2.28；没有据此声称所有2.28系统都已运行通过。构建使用 GCC 10.2.1（Alibaba 发行）、GNU Make 4.2.1、binutils 2.35、Ninja 1.8.2、pkg-config 1.4.2、Python 3.11.11和Meson 1.9.0。工具入口字节和版本已记录，但系统头文件、cc1及完整系统依赖没有全部冻结，这两次一致性只证明当前环境，不构成跨机器完全封闭构建。

实际失败与处理保留在任务记录：run01/02输出位于共享可写祖先下，私人目录检查在编译前拒绝；新增反例促使创建前就按私人路径规则检查祖先，未改变工作区权限。run03进入断网编译后发现系统 `ld` 经 `/etc/alternatives` 间接解析，未挂该目录导致链接失败；使用 GCC 公开 `-fuse-ld=bfd` 选项，显式记录已挂载 `/usr/bin/ld.bfd`，没有扩大挂载或修改源码。run04/05在此修复后完成。

候选以最后写入的 `candidate.json` 为有效性标记。若归档写入后该标记因磁盘错误失败，可能留有孤立归档；下游必须要求完整候选记录并核对摘要，不能只因归档存在就接受。这一失败切点已由假构建器测试覆盖。

## 显式导入与现代资产来源

`scripts/import-pi-bwrap.py` 读取已有候选、固定三份输入和归档中的完整许可证，全部校验及目标预检完成后才排他写入现代家族。它不运行编译器或生成的 helper，不修改 dependencies/manifest，也不激活实例：

```sh
/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python -B scripts/import-pi-bwrap.py \
  --candidate .cache/pi-two-profiles/candidates/bubblewrap-0.13.0-linux-x86_64 \
  --sources .cache/pi-two-profiles/candidates/bubblewrap-build-inputs
```

输出是供正式依赖声明使用的公共 source JSON。来源继续使用 `kind: asset`、`format: tar.gz`，以 `build_record: {recipe, path, digest}` 引用记录，不声明二进制下载 URL；URL 与 build_record 互斥，v1 禁止 build_record。当前唯一固定配方为 `bubblewrap-v1`，绑定 Linux x86_64、`bin/pi-bwrap`、三份输入及仓库构建脚本；新配方需要显式版本和校验实现，不接受任意构建命令。

记录保存在 `locks/pi-modern/build-records/<digest>.json`，归档保存在 `vendor/pi-bwrap-<archive_digest>.tar.gz`，输入同样内容寻址；许可位于 `agents/pi/build/licenses/bubblewrap-0.13.0/COPYING` 与 `libcap-2.77/License`。本次真实导入七个文件，共1,472,404字节；只读复核得到的二进制摘要与构建表一致，记录摘要为 `5308fbf91bf839b3559f157e0552382a8d3dd93c29a275cb85b17ef31a3f00b7`。这没有执行二进制或生成真实 Base manifest。

已有相同内容的0600/0644公共文件允许复用，保留其权限；新文件0600，目录0700。冲突、链接或可被组/其他用户写入的文件失败，不覆盖。中断可能留下已验证的内容寻址片段，下次补齐；这不是跨文件事务，片段不代表可激活运行包。

锁读取、生成前后和安装分别检查记录、固定输入、归档及许可证。记录拒绝重复JSON键、未知字段和不固定的配方；归档有压缩/展开限额，只允许精确四个普通条目、固定模式和内嵌记录，拒绝链接、重复、额外条目及tar结束后的隐藏内容。安装对实际复制的许可证字节再次核验，避免校验后重读发生替换。`fetch-pi-assets.py --profile pi-base` 对自建来源仅做这些检查；即使 `--force` 也不会删除损坏文件、下载替代物或运行构建器。缺失必须显式构建/导入。

本地构建记录绑定可审查的输入、脚本和输出；它不是外部构建证明或签名，也不是运行许可。有人能同时改写锁、记录和校验代码时，本地摘要不能替代外部信任根。

## 必须分别验收的边界

- 源码校验：固定来源、路径、限额和许可证已由合成测试及真实归档只读解析检查。
- 构建：当前环境两次实际编译、静态依赖检查及字节一致性已通过；生成二进制不表示行为通过。
- 正式安装：需完整来源及产物锁、选定能力绑定、安装检查和精确 Base 文件集合。
- PID 生命周期：需真实入口检查初始化进程、后代终止和退出恢复。当前宿主参数仍有 `--bind / /`，只承担进程生命周期范围，不能称文件系统/网络沙箱。
- 工具隔离与整进程保护：继续按 T033–T040 独立实现和验收，不由构建或 PID 命名空间证据替代。

宿主启动前会检查本地安装收据，spawn 前再次核对所选 helper、门控脚本、profile 与收据中的内容和身份。该收据不是外部签名，不能抵御有同 UID 写权限的主体同时改写二进制和收据。受管工具拒绝写运行包；未隔离的恶意同 UID 扩展属于整进程威胁边界，不能因这次局部检查宣称已解决。
