# 单一 owner codec 的固定运行包映射

2026-10-07，root 从已独立接受的 launch 来源决策提取下一小包。此包只使已有 runtime_files 接口能固定安装同一自有 codec；不加入 Node source、不生成正式锁、不改变 profile 选择、不打开 factory、不实现 resolver 或 controller／Db。

## 唯一变更

可写 `src/agentcfg/pi_runtime_files.py` 和新增 `tests/test_pi_owner_codec_runtime_file.py`。既有测试、所有 guard、codec／record／store／新 window、依赖声明／schema／lock和原生材料保持原字节。只有唯一 writer 在前包 STOP 后修改；root 是文档和状态唯一 writer。输入原 module SHA `5ef413cf5121479e32774f89b8967aabc9ab2b2887bf8f6aee2805acdb98c066`／6432B；source codec SHA `ae51f5ab739a80006639feead7b22822c5f135430e41926f59420ec2127a1238`／8790B。

在 `_validate` 的 source 选择中只加入 literal exact 分支：source `agents/pi/packages/durable-service/src/owner-message.ts`，expected target `runtime/durable-owner-message.mjs`，transform `ts-module`。其余校验和函数原样：未知字段／source／path／transform失败、排序与唯一目标、input/output digest、mode600、原 Tree 读写与完整 inventory。不能用泛化 regex 允许整个 packages 或任意 src，也不引入 role字段、公开 resolver、dynamic import扫描或新的转译器。

沿用原 `_content` 的 ECMAScript子集 `.ts`→`.mjs` 引用改写；该 codec 当前仅 import Node builtin，原 source字节应等于 transformed bytes。须用实际原 codec／hash断言这项有限事实；它不等于运行了 transformed module或验证以后新增依赖。将来codec改相对引用、角色或代码，source/recipe/runtime身份与相关qualification重新核验，不复制协议实现到runtime。

## 默认验证与材料

新 tests 使用现有 conftest 原临时 HOME、断网、fake subprocess守卫。实际 temporary Tree／写入的自有 codec bytes可验证原 lock_files/install_files/validate_files闭环；不执行 Node／SDK／SQL、真实服务、proc、信号或 locks。package fixture仅虚构 metadata，不冒充正式 Node／accepted selection／真实部署。

先保存完整原6432B source，写完整新 tests后在原 source运行，再实现单一分支跑相同final suite；正例在旧 source拒绝须是真实行为失败，不把 import／环境／fixture失败算 red。常规fixture修复单列保存，不改原 guards或断言来凑通过。至少覆盖：exact row在 declaration／locked modes；同一真实codec input/output摘要、installation bytes与mode600、完整验证；source typo／同目录其他文件／子目录／其他package拒绝；target／transform不同和unknown key拒绝；duplicate target；stale原source／transformed digest／installed content拒绝。只新增 source分支，失败映射仍沿用现有 ConfigError，不在本包顺手改共有JSON或错误链。

限定 scout 静态证据 `/tmp/pi-owner-codec-runtime-file-tests-evidence.md/.json` 已确认直接既有套件为 `tests/test_pi_runtime_files.py`，并记录其他更广锁／sync调用点；本包选择直接受影响路径，不执行全仓。固定 same-final old→new 命令 `/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python -m pytest -q tests/test_pi_owner_codec_runtime_file.py tests/test_pi_runtime_files.py`。保留每次完整stdout/stderr、首末 source/test/dependency/guard pins、完整 source diff、旧source same-final red与最终green独立计数；同次run按新增套件／未改直接套件分别报告。green稳定后 root及不同executor只审该diff与受影响路径；无新证据不扩大／反复全量验收。

目前本文只固定窄包目标，独立设计审查和root明确实现授权仍在实施前完成。正式7/100与所有产品／owner／Db gate保持原状态。
