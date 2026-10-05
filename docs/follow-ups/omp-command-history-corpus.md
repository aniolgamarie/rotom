# 历史命令解析回归集

本轮在 `test/omp-command-history` worktree 中开发，基线 `139b277`。用户授权只读提取 Pi、Codex、OMP 的历史命令，脱敏后用于验证当前普通 Bash 审批解析器。原始命令、用户提示、工具输出、账号库和凭据不进入仓库；不会执行任何历史命令、启动 agent 或调用模型。

## 验证范围

测试对象为 `standalone-shell-analysis.ts` 中的纯解析函数及模式匹配函数，不是宿主 Shell 执行器。历史记录只证明命令曾被提交，不能证明执行成功、低风险或获得授权。解析完成也不等于自动批准。

两种集合分别维护：

- 本机私有候选语料：显式指定日志根，流式读取已知工具事件，只提取命令。脱敏、去重后保存在 0700 私有缓存目录内的 0600 文件。自动脱敏不是公开发布保证，命令内嵌代码、未知高熵值和未支持载体必须隔离并单独计数。
- 仓库内固定回归样本：从候选语料的语法形状中人工选择、用虚构路径和参数重建，并独立标注预期命令/参数/连接符或保守拒绝。这些样本不保存真实机器路径、项目数据、原文指纹和日志文件名。

统计必须包含三种来源的文件数、命令事件数、脱敏后唯一命令数、未知载体/坏记录/隔离数量，以及解析完成与拒绝数量。拒绝不能算成语法覆盖成功。已知未支持语法与必须保持拒绝的动态结构分开标记；接受率不是解析准确率，也不是风险审批准确率。

## 验收重点

支持样本检查完整的 argv 和连接符，不能仅检查“没有抛异常”。混合读取/写入的复合命令必须提取后续命令，不允许只看开头。引号中的分隔符、转义、管道、布尔连接和目录切换均有固定预期。动态替换、控制结构及截断输入检查失败边界。通配符、重定向和多行命令作为当前覆盖缺口显式报告，不以白名单或删掉解析守卫掩盖。

提取器使用虚构日志验证凭据哨兵、文件权限、去重、错误载体、输入不变及不执行命令；默认测试不读取真实 HOME。真实日志提取是本轮单独授权的只读步骤，后续默认 CI 只使用固定样本。

## 提取和重跑

`scripts/omp-command-history.py` 没有默认 HOME 搜索路径。每个来源可重复传入 `--pi-root`、`--codex-root`、`--omp-root`，输入只能是显式 JSONL 文件或目录。输出只能是仓库 `.cache` 或系统临时根（包括 `/tmp`）内的私有子目录，独占创建且拒绝子路径符号链接和覆盖已有文件。系统临时根的官方别名会规范化，临时根即使指向仓库公开目录也不能输出。不要将候选文件改为公开 fixture。

Pi/OMP 只读取 assistant 的已知 Bash 工具事件；Codex 支持 JSON 工具参数和显式开启的 JavaScript 静态提取。JavaScript 必须成对提供 `--bun` 和 `--js-parser-module` 的绝对现有文件路径。后者是受信的本机 `@babel/parser` 模块，不是历史文件；代码通过公开 [Babel parser API](https://babeljs.io/docs/babel-parser) 解析历史文本，绝不求值。没有这两个参数时，JS 载体计为 unsupported，不会猜测命令。

JS 仅提取字面 `tools.exec_command({cmd: "…"})` 或不含插值的模板字符串；变量、拼接、展开、别名、解构、可选调用等不推断。无法解析的引用/调用点记入 `jsUnresolvedCalls`，这个字段包含引用点，不能当作实际执行次数。AST 中找到的调用也可能位于不会执行的分支，因此只能称为候选命令。

```bash
.venv/bin/python scripts/omp-command-history.py \
  --pi-root /explicit/pi/sessions \
  --codex-root /explicit/codex/sessions \
  --omp-root /explicit/omp/sessions \
  --bun /explicit/bin/bun \
  --js-parser-module /explicit/node_modules/@babel/parser/lib/index.js \
  --output .cache/command-history-private/candidates.json

bun scripts/check-omp-command-history.ts \
  --corpus .cache/command-history-private/candidates.json

.venv/bin/python -m pytest tests/test_omp_command_history.py -q
bun test tests/omp_command_history.test.ts tests/omp_command_history_js.test.ts
```

纯解析测试不依赖 Babel 或宿主 SDK。默认 JS 测试使用合成 AST，真实库集成用例明确 skip；只有显式设置 `OMP_HISTORY_JS_PARSER_MODULE` 为已准备的解析模块时才执行该用例，输入仍全部虚构。现有 Python CI 自动收集提取器测试；新增 `omp-command-parser` job 固定 Bun 1.4.0 跑合成回归和缺口报告。setup action 固定为官方 [v2.2.0 commit](https://github.com/oven-sh/setup-bun/commit/0c5077e51419868618aeaa5fe8019c62421857d6)，不安装或运行 OMP、Pi、Codex。

自动脱敏会排除大量内嵌代码、动态结构、高熵串和无法可靠确定边界的值；路径/秘密归一化也可能合并不同原始命令。因此私有集合存在选择偏差，不能反推完整历史的支持率。坏引号可能在脱敏阶段已跳过，固定样本另外检查这类截断边界。未知日志格式无法全部识别，统计不声称完整捕获所有工具调用。

## 已确认的解析问题

固定集合共 79 条：39 条完整拆分、23 条动态/无效语法拒绝边界、14 条当前覆盖缺口、3 条注释语义错误。前三类检查当前合同的稳定性；拒绝边界和覆盖缺口都不计作语法覆盖成功。后 3 条保持 Shell 语义的正确预期，报告 `semanticConformancePassed=false`。

- `echo ok # note`：注释被当作 argv。
- `echo ok # $(id)`：注释内字符触发不支持判断，而不是被忽略。
- `printf '%s' value # ; rm -rf /`：注释里的分号被当作后续命令。

这些字符串只做纯函数输入。本轮没有修复生产解析器，也没有刷新权限包身份、锁或本机部署。后续应先修复注释词法处理，再分阶段扩展通配符、`2>/dev/null` 等明确重定向和多行语法；使用固定正确预期与历史语料共同验收，不能将守卫整体删除来提高接受率。

## 2026-10-05 验收结果

最终保存的私有候选包含 31,742 次命令出现、跨来源去重后 16,103 条。当前解析器接受 8,640 条、拒绝 7,463 条、抛异常 0；接受率 53.65%，受上文脱敏选择偏差影响，不是完整日志支持率。来源内唯一数存在跨来源重叠，不能直接相加。

| 来源 | 日志文件 | 保留命令出现 | 来源内唯一 | 接受 | 拒绝 |
|---|---:|---:|---:|---:|---:|
| Pi | 594 | 20,769 | 8,337 | 2,911 | 5,426 |
| Codex | 1,052 | 10,958 | 7,792 | 5,755 | 2,037 |
| OMP | 11 | 15 | 8 | 7 | 1 |

脱敏阶段跳过 61,952 次候选命令；未知/不支持载体按记录计数，命令出现按字符串计数，两个单位不能相加。Codex 静态分析了 39,006 份 JS 文本，找到 41,387 个字面命令候选，未解析引用/调用点 1,271 个，坏 JS 45 份。固定集合确认 3 个注释错误；历史集合的局部注释 oracle 可判定输入为 0，不能据此声称历史注释正确。

提取器与隐私合成测试 53 pass；显式已有 Babel 集成 90 pass / 401 assertions；无 Babel 默认测试 89 pass / 1 明确 skip / 388 assertions；现有 standalone/native 64 pass / 543 assertions。默认与显式测试区别只在真实 Babel 集成用例，历史评测另行授权且未执行任何命令。GitHub workflow YAML 本地校验，远程 CI 尚未运行；实际 macOS 和 Windows 未运行，Windows 提取暂不支持。

实际工具链为 Linux x86_64、Python 3.11.11、Bun 1.4.0、Babel parser 7.29.9；未下载新工具链。executor 为 gpt-6.1-sol / medium，scout 为 gpt-6-luna / high。独立审查发现并修复 curl 用户/代理认证与 OAuth 值遗漏、JS 别名统计遗漏；系统临时根用合成测试验证，真实平台不计作通过。

机器可读的[汇总证据](../acceptance/omp-command-history-20261005.json)只含数值和固定样本身份。最终私有语料保存在 main 的 `.cache/omp-command-history/20261005/candidates.json`，0700 父目录/0600 文件，未纳入 git；同目录保存不含命令的 `parser-report.json`。本轮中间导出已清理，原始日志未写入或删除。日志可能持续追加，本节是已保存候选集合的快照，重提取的数量可能改变。

## 任务记录

| 状态 | 内容 |
|---|---|
| 完成 | 独立 worktree；三来源只读提取、私有脱敏语料、公共固定样本、纯解析评测、隔离 CI 配置、独立审查与修复 |
| 进行中 | 无本轮实现工作 |
| 失败待决策 | 无交付阻塞；生产解析器的 3 个注释错误及 14 条语法缺口已记录，修复需作为下一轮行为变更 |
| 环境不足未验证 | 远程 CI、真实 macOS/Windows；智能审批准确率、真实宿主行为和跨平台 Shell 执行不属于本轮通过结论 |
