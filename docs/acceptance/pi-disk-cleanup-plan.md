# 磁盘清理方案（待用户确认，未执行任何删除）

更新日期：2026-09-21。编制依据：T112 逐项证据登记的材料需求核对 + 归档完整性核验。

## T112 登记还需要从运行根提取什么

逐项核对结论（最终候选 ea6f04b2）：

| 材料 | 来源 | 是否必须运行根 |
|---|---|---|
| 每配方 identity 五元组（锁/runtime/策略/资源/机器契约） | **新冷目标**（run2 根下 ea6f04b2 部署实例的 `load_workspace`+`diagnostic_identity`） | 是（run2 根，届时提取后落盘可脱离） |
| EvidenceRecord 时间戳（started/finished） | 新冷目标各 case 的 input.json/controller-result.json mtime | 是（提取后落盘可脱离） |
| mock 证据 | 已归档 `docs/acceptance/agentcfg-pi-mock-*`（含 .artifacts 原始输出） | 否 |
| 冷重建证据（报告/native明细/step输出） | 归档时复制进 `docs/acceptance/pi-cold-<锁>/` + index.json SHA | 否 |
| 候选/平台/阻塞记录 | docs/acceptance 下 JSON/Markdown | 否 |
| 失败过程证据（7942277e sync失败、attempt1 recovery回归、r3 readseek未接线） | 已提取小体量证据（attempt1-evidence/、r3-evidence/ 在 run2 根，每个 <1MB） | 提取后否 |
| 终止证明（lease reclaimed/v3 terminated） | 已从运行根统计并写入平台记录（82/82、92/92）；原始 lease/process 记录属"运行态"，非登记输入 | 否 |

结论：**旧运行根 `run.9EvW7wDS` 对最终 T112 登记不是必需**——它的候选（4c043f8f）已被 ea6f04b2 取代，身份不可继承；其证据已全部归档或已被取代。run2 根在登记材料提取完成后同样可清理。

## 可清理目录与预计释放

| 目录 | 大小 | 内容 | 释放 | 核验依据 |
|---|---:|---|---|---|
| `~/.cache/agentcfg-pi-handoff/run.9EvW7wDS` | **111G** | 4c043f8f 轮完整运行态（安装树/部署实例/租约记录/retired失败目录） | 111G | 证据已归档：`pi-cold-4c043f8f/`（184文件+SHA索引已复核）、mock/候选/平台记录齐备；失败过程证据 `retired-7942277e-sync-fail-*` 的**报告级**内容建议先提取保留（<10MB） |
| `~/.cache/agentcfg-pi-handoff/run2.mSLsYCX7/pi-*`（各配方完成后） | 每配方 15–25G | ea6f04b2 运行态 | 60–100G | 冷证据归档进 `pi-cold-ea6f04b2/` + SHA 索引；身份/时间戳提取落盘 `docs/acceptance/pi-evidence-identities-ea6f04b2.json` 后脱离 |
| `~/.cache/agentcfg-pi-handoff/clean3.rDp1lF3k`、`clean.N6uts4mW` | ~155M | 干净环境交付验证副本（含已下载的2个github资产） | 155M | 交付验证记录已写入 `pi-vendor-deliverability.md` 与实施记录 |
| `cache/pi-validation/runtime-volume`（仓库内，**已git忽略**） | 142G（在 /data，非 /home） | 更早期各候选的沙箱卷 | 142G（/data） | 其中 `cold-*-484f07e9/candidate-source` 是 484f07e9 冻结manifest的唯一磁盘副本（候选记录有摘要无全文）；归档该文件（<1MB）后可清。旧候选运行态无登记价值 |

保留不动：仓库本体（含 `locks/pi/vendor` 1.68G 资产——重建需数小时下载，本身是可交付输入）、`~/.local/share/agentcfg-pi-tools`（锁定工具链 ~600MB）、`docs/acceptance/` 全部归档。

## 建议操作顺序（待确认后执行）

1. 从 run.9EvW7wDS 提取 `retired-7942277e-sync-fail-*` 的两份冷报告JSON（<1MB）到 docs/acceptance。
2. 删除 run.9EvW7wDS（释放 /home 111G）。
3. ea6f04b2 冷重建完成后：归档证据 + 提取登记材料，删除 run2 的 pi-* 大目录（释放 /home 60–100G）。
4. 仓库 `cache/pi-validation/runtime-volume`：归档 484f07e9 candidate-source 的 locks 副本后整体清理（释放 /data 142G）。
5. 两个 clean* 目录随 run2 根一并清理。

预计释放：/home 约 170G、/data 约 142G。全部删除前逐项核验对应归档的 SHA 与清单。
