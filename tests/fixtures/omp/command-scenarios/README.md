# 公开 Shell 场景测试集

`corpus.json.gz` 是由私有历史词法场景**重新构造的虚构测试数据**，不是私有文件的公开副本。
没有日志来源、机器/会话路径、原始命令指纹或 provider 信息；普通词、数据、数字与程序
字面内容由固定公共词表及 fixture 参数重建。Shell 的引用/转义、运算符、空值、glob 和
重定向语法保留；已知危险命令、选项及根/系统目标按公开常量保留。
重建后相同用例合并并累计 `representedScenarios`，全部11,504个私有场景均被计入。
原始私有场景另行做只读纯解析比对，不公开其命令文本。

每条记录包含合成文本的 SHA256、分类、特征、代表场景数、独立 `expected` 解析结果与
`expectedGate`。gate 预期限定 smart、native allow、真实来源的虚构用户消息、无额外
配置限制；其它模式、deny/prompt、取消及上下文改变由插件单测独立覆盖。
`expectedGate=human` 在 headless 测试中必须阻止且不能调用模型/委托；model 路径恰审查一次、
委托一次并保持原参数。模型和原生执行器均是假实现，不实际执行任何命令。

预期来自 `scripts/omp-shell-test-oracle.py` 的有界语言合同。它使用标准库 shlex 解码，
不导入生产解析器；79条另外硬编码的语义 anchors 检查 quote、connector、注释等规则。
一致性、拒绝和假模型验证不能证明任意Shell程序语义或真实审批质量。
没有为了提高接受率将动态/未解析结构标成自动批准。

生成工具：`scripts/rebuild-omp-test-corpus.py`，只读取显式授权的私有输入；输出位置限定
在本目录，新建且拒绝覆盖，gzip 固定 mtime 并不保存原始文件名。普通 CI 直接读取已提交
集合，不需要真实 HOME/日志、网络或重新提取。不会求值输入中的 Shell、JavaScript 或代码。

验证：

```sh
bun test ./tests/omp_shell_scenarios.test.ts \
  ./agents/omp/packages/omp-permission-control/standalone.test.ts
.venv/bin/python -m pytest tests/test_omp_public_corpus.py -q
```

当前冻结集合：11,473条公开用例，代表11,504个原私有场景；9,442条静态解析、2,031条
明确拒绝边界。默认fake配置下9,430条走模拟模型/委托，2,043条走headless人工阻止；
其中12条虽然可静态解析，但含凭据信号，不发送给审查模型。
文件1,223,214字节，约1.17 MiB；固定词表/fixture atoms检查中未发现未知数据词或已知身份残留。

完整纯解析汇总：`bun scripts/check-omp-shell-scenarios.ts`，任何oracle差异、异常或不一致
metadata都失败。插件入口机制仍由上文的standalone测试单独验证。


## 2026-10-09 严格验收

历史集合与 v1 oracle 保持冻结；旧 `human` 标签不能被解释为“普通语法支持已完成”。
普通 HOME 参数和 `command -v/-V` 查询升级只允许固定 583 行发生变化：

- `grammar-upgrade-20261009.json`：固定 ID、原行摘要和 gate 差量。
- `grammar-parse-upgrade-20261009.json`：同一批 ID 的独立完整结构预期，检查 argv、
  connector、HOME/glob 下标和重定向顺序；由独立 Python v2 oracle 生成，不能从生产解析器生成。
- `strict-acceptance.json`：20 条独立手写完整结构，其中 17 条普通可审查场景、3 条受原生
  保护的危险复合场景；42 条人工边界各放入 4 种上下文，合计 168 个边界组合。

验收分别统计可审查普通场景和人工边界。普通场景在假模型允许时必须审查一次、原参数委派
一次且不询问；假模型 ask/deny 或原生 deny/prompt 必须阻止委派。人工边界必须在模型前
阻止；不能仅凭“与旧解析器相同”算作普通场景验收。新增差量有固定整体、来源和原行摘要，
其它 10,890 行继续按原完整结构验收，不能自动重生标签消除失败。

```sh
bun test ./tests/omp_shell_scenarios.test.ts ./tests/omp_shell_strict_acceptance.test.ts \
  ./agents/omp/packages/omp-permission-control/standalone.test.ts \
  ./agents/omp/packages/omp-permission-control/native-bash.test.ts
.venv/bin/python -m pytest tests/test_omp_public_corpus.py tests/test_omp_shell_review_oracle.py -q
bun scripts/check-omp-shell-scenarios.ts
```

新版假配置 gate 预期是 10,013 条审查、1,460 条人工边界。该数字描述声明的静态语法，
不表示所有合法 Shell 语法都受支持。静态赋值前缀、`command -p -v`/`-pv`、动态展开、
控制流及未支持执行上下文仍有明确能力边界；这些拒绝不应计作普通功能覆盖成功。
此验收不运行集合中的命令、不读取私有日志或真实凭据，也不证明真实模型判断质量、
真实宿主集成或已部署会话正在使用新版代码。
