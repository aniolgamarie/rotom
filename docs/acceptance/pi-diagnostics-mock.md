# Pi 诊断与证据门槛：代码/mock

2026-09-18 定向运行以下测试，80 passed：

```sh
.venv/bin/python -m pytest -q \
  tests/test_pi_doctor.py tests/test_pi_web.py \
  tests/test_pi_evidence_schema.py tests/test_pi_release_gate.py \
  tests/test_pi_optional_capabilities.py tests/test_pi_upgrade.py \
  tests/test_pi_verification_cli.py tests/test_pi_capability_manifest.py \
  tests/test_pi_catalog_schema.py
```

- 可选能力覆盖 Cursor/Bun 选择、Node managed 拒绝、OpenSpec 实际资料、缺依赖/未选 backend、MCP/Web 显式路线与凭据引用。
- CapabilityEvidence 区分 mock/native/live 及 passed/failed/not-run；身份包含锁、运行时、角色/资源、策略和机器契约。身份或平台变化使旧证据 stale。
- AcceptanceScope 保留固定选择理由，禁止因失败删除或缩小必需范围；软件验证不能改成可选账号未选择。报告五态与证据三态分离，缺证据不能批准。
- doctor 分开输出配置/部署/依赖、加载/执行证据及四种认证状态。bootstrap 未绑定、缺包、未选 backend 和待登录分别报告；不读取真实账号推测状态。
- `doctor --live` 的测试只用假 HTTP 连接和假探测器，验证 HEAD、明确路线、无认证内容及不调用模型。Web 公共抓取无目标时不猜站点；配置为公共页面且无凭据时认证为 not-required。

T090、T092、T093 的代码/mock 检查完成。这里不代表真实 `--live`、native 或账号通过，也不完成后续 T098 的原生场景 runner、T101 的最终维护流程总验收。
