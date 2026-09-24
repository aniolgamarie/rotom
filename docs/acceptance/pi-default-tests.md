# Pi 默认测试记录

## 2026-09-20 当前批次

- 仓库候选锁：`484f07e9f16e070296b88ba24dcf7a5900f9d098ed1d5f43340c4f31b281dd26`，四配方、38 来源；DSH 锁逐文件保持不变。
- 命令：`scripts/verify-pi.py --tier mock --case all`，由仓库 `.venv/bin/python` 执行，Node 使用固定 24.14.0。
- 报告：[完整报告](agentcfg-pi-mock-20260920-host-namespace.json)，原始输出保存在同目录的 `agentcfg-pi-mock-20260920-host-namespace.json.artifacts/`。
- **结果：1782 Python tests + 7 subtests、325 Node tests 全通过**。
- Python 使用临时 HOME、网络与第三方进程替身；Linux Node 测试位于 bwrap 的只读仓库、独立可写临时目录和隔离网络中，另有网络/进程 guard。
- 覆盖配置与部署、DSH 回归、model-delegate、Task Keeper 协议与监督、服务适配、ReadSeek 源码构建替身、Pi宿主/Codex PID命名空间证明、验收报告、失败分类及发布门槛。默认测试不启动 Pi/Codex 等第三方宿主，也不访问真实账号。

安装代理仅进入下载/构建环境，原生场景与模型环境不继承；系统 CA 的入口和真实目标都保留，未关闭证书验证。对应冷重建正在单独执行，其结果不能从本文件推定。

本记录不代表四个平台已通过，也不代表真实账号和完整迁移获准发布。以固定 scope 的 [支持矩阵](pi-support-matrix.md) 和 [发布检查](pi-release-decision-20260920.json) 为准。

补充的锁固定后复验被自动审核超时和默认沙箱属主映射问题阻塞；后一次默认沙箱尝试未通过，详情见 [阻塞记录](pi-validation-blockers-484f07e9.md)。此前有效隔离报告保持原样。

## 2026-09-21 4c043f8f 候选（本机Pi接手后）

- 仓库候选锁：`4c043f8fa2f52cc7b198a030c51f814ba937c405da100331ed75bd8a73993424`（T098接线与6个linux/all资产vendored后重新冻结；相对484f07e9仅控制代码、dependencies.json的6个vendor_path与对应manifest身份变化，profile_slices与全部依赖解析逐字节不变，DSH锁未变）。
- 命令：`scripts/verify-pi.py --tier mock --case all`，仓库 `.venv/bin/python`，Node/Bun 使用独立锁定工具链（Node v24.14.0、npm 11.19.1、Bun 1.4.0，见实施记录）。
- 报告：[完整报告](agentcfg-pi-mock-20260921-4c043f8f.json)及同目录 `.artifacts/`。
- **结果：1787 Python tests + 7 subtests、325 Node tests 全通过**（新增5项为T098平台门控/slot/helper契约替身与负向回归）。
- 同日中间候选7942277e的同规模mock亦通过（[报告](agentcfg-pi-mock-20260921-7942277e.json)），该候选因资产下载不稳定被vendored后的4c043f8f替代，未产出原生证据；另一次整库运行出现单例`st_atime`跨秒竞态失败，单测复验6/6通过，详见实施记录。
- 本记录仍不代表四个平台已通过、真实账号可用或完整迁移获准发布；冷重建与原生结果以平台记录为准。
