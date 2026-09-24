# ReadSeek 边界适配的默认回归

日期：2026-09-18。层级：mock。未执行第三方宿主、原生 ReadSeek、真实账号或模型。

## 完整默认回归

```sh
.venv/bin/python scripts/verify-pi.py --tier mock --case all \
  --output /tmp/agentcfg-pi-mock-20260918-readseek-boundaries.json
```

- 开始：2026-09-18 06:56:07 UTC。
- 结束：2026-09-18 07:01:33 UTC。
- pytest：1358 passed，7 subtests passed，退出 0。
- Node：211 passed，0 failed，退出 0。
- 总报告：`status=passed`，仅限 mock。
- 环境：Python 3.11.11；统一 mock 的 Node 为 v24.1.0，不能作为锁定的
  Node 24.14.0/Bun 原生运行证明。

机器上的详细输出位于 `/tmp/agentcfg-pi-mock-20260918-readseek-boundaries.json.artifacts/`。
这些临时文件用于本轮检查；最终候选身份和正式发布报告尚未冻结。

## 额外检查

- Python 定向 ReadSeek/GuardedFiles/vendor：51 passed。
- 固定 Node 24.14.0 的 ReadSeek 隔离测试：8 passed。
- 固定 Node 24.14.0 + Jiti 2.7.0：原九工具只登记、不执行，参数契约匹配。
- 六个 ReadSeek runtime 源文件按安装器规则转为 `.mjs` 后语法检查通过。
- MCP 完整源码 TypeScript 检查通过。
- MCP、ReadSeek 补丁相对原始 npm 包的 dry-run 均退出 0。

## 覆盖与局限

新增覆盖包括工具包装、受限 worker 注册与取消、计算产物身份、只读/路径/删除拒绝、
源文件变化、撤权、多文件提交日志、anchors 更新以及 Git 类别选择。
完整套件同时执行已有 Pi 与 DSH 默认回归。

ReadSeek 监督器控制器、Git/rg 实际监督选择、原生/视觉资产和完整九工具原生验收仍未完成。
web 适配、最终依赖锁、平台和实网验收仍在剩余任务中；T086 保持未勾选，总计 87/112。
其他三个目标平台按用户决定继续未验证。本记录不代表完整迁移或发布批准。
