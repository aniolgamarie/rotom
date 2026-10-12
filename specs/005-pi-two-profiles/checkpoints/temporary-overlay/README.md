# 未应用的 temporary-overlay 候选

`proposal.patch` 是中断时独立候选树相对于本开发检查点正式源码的差量，共10个文件；`manifest.json`保存每个文件的base/candidate SHA256及patch摘要。没有复制整个本机cache、字节码、账号或运行状态。

这份候选尚未冻结验收，也未应用到生产源码。首轮多文件生产编辑被自动审批拒绝：实现未闭合，可能引用缺失的overlay helper，审核认为持久安全边界变更的材料不足。随后仅在独立候选树继续实施；中断时没有完整绿色验收。patch的存在不是应用授权或对拒绝的绕过。

下一步在新的临时来源副本中核对manifest的base哈希，阅读STATE中的已决定接口，补全FD/来源/系统别名/模式传播和测试，然后稳定审查。`tests/test_pi_temporary_overlay.py` 是相应未应用功能的RED用例；不应通过删除守卫或复制秘密获得绿色结果。

原设计证据集中在STATE、implementation-status和已有checker/InputSnapshot契约。原机 `.cache` 的日志和原像仍只在原机；本portable patch保留候选代码进度，不携带原机审阅资格，也不保证能直接应用到将来更改过的源码。
