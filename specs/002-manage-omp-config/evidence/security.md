# OMP 秘密与归属边界

日期：2026-09-24。所有秘密均为合成哨兵，没有读取真实凭据。

```sh
.venv/bin/python -m pytest -q tests/test_omp_secret_boundaries.py tests/test_deployment.py --tb=short
```

**26 passed in 9.60s**。新增capture门控覆盖无deployment、绑定不符、活动实例、pending；精确按已部署profile读取，不扫描另一profile偏好。

实际负向测试发现rollback只检查本轮变更叶子，会遗漏同一OMP文档中未参与回滚的认证字段字面漂移。修复后，rollback先验证所有当前OMP认证叶子，再执行备份回滚；plan/capture/doctor同样拒绝原生字面secret。状态/cache/输出/异常均无秘密哨兵。历史current/previous/pending删guard后不能绕过强制路径/selector分类。

首次测试另有3项selector=None的测试代码错误，修正后历史测试3项独立通过；该错误不计实现失败证据。盘点还在完整候选资源中执行敏感模式和已知秘密扫描，auth/session/数据库及旁文件不读取；见[迁入证据](us3.md)。任意未知文本的秘密判定仍需人工审阅，扫描不声称完全证明。
