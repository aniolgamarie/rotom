# ReadSeek 监督控制链验证

2026-09-18；mock 及独立依赖安装检查，没有执行第三方宿主、原生 ReadSeek 或真实模型。

## 当前源码默认回归

```sh
.venv/bin/python scripts/verify-pi.py --tier mock --case all \
  --output /tmp/agentcfg-pi-mock-20260918-readseek-controller.json
```

- 开始：2026-09-18 07:57:00 UTC。
- 结束：2026-09-18 08:02:47 UTC。
- pytest：1390 passed，7 subtests passed，退出 0。
- Node：216 passed，0 failed，退出 0。
- Python 3.11.11；统一 mock 的 Node 为 v24.1.0，不代表锁定 Node/Bun 的原生认证。

新增测试覆盖正式 RPC 准入、同一租约内的目录驱动、子目录作用域、固定 Git/rg 查询、
先核验提交再确认退出、取消及未知终止、大结果分块、会话切换和文件上限。
所有第三方 subprocess/exec 均被替换，第一方 driver 的真实导出回调使用临时文件。

另有固定 Node 24.14.0 下 24 项定向回归及安装规则下九个 runtime 模块语法检查通过。

## 中间候选的真实锁与安装检查

独立源码副本：`/tmp/agentcfg-pi-lock-probe-hg_lcmmz`。
24 个来源和四配方的在线锁解析通过，中间锁 identity：

```text
2f68db97fc2911cf11698bc6f250d982a837f3139fed348f6023152e7b10abd3
```

全部安装使用 `npm ci --ignore-scripts`、独立临时 HOME 和实例，运行包密封状态为 installed：

| 配方 | 临时安装目录 |
|---|---|
| pi-default | `/tmp/agentcfg-pi-readseek-install-5ukytsi9` |
| pi-managed | `/tmp/agentcfg-pi-readseek-install-ul8e81qy` |
| pi-codex | `/tmp/agentcfg-pi-readseek-install-1kkibb1p` |
| pi-cursor | `/tmp/agentcfg-pi-readseek-install-9_n0wz0c` |

本机投影的 ReadSeek Linux x86_64 二进制 SHA-256：
`8d3a221eb45badea3dc0550a5b08f6abf09a47d8fd95b345cb8adf5b9a8ae1c4`。
安装包含原生许可与来源说明；没有运行该二进制。

该副本早于随后补充的只读媒体上限和旧工具失效检查。
这些安装记录不能直接成为最新源码或最终候选的安装证明；后续改动由当前源码 mock 覆盖。
仓库最终锁尚未写入。macOS x86_64 源码构建、视觉资产及 native/live 验收仍待完成。
