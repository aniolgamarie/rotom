# 文本、结构与语义证据

| 方法 | 适合的命题 | 前提和限制 |
| --- | --- | --- |
| 文本搜索 | 某拼写、调用字面形式或文件存在 | 注释、宏与字符串可能同样命中，不确认语法或类型 |
| ast-grep查询 | 某类语法形状、参数结构或局部模式 | 项目已提供并核实CLI；语法树匹配不确认C++重载/模板实例化结果 |
| 编译器/既有clangd | 当前编译参数下的类型、引用或诊断 | 需要正确工具链与compile_commands.json；缺依赖或flags不能当语义通过 |

合成示例：`demo(value)`的文本命中可能在注释中；AST调用模式可以排除注释，
但要确认调用的是哪个`demo`重载，仍需要编译条件。不要把AST改写预览直接应用到项目。

项目工具已核实并且公开help确认相关flags后，可针对一个已批准的小文件查询：

```sh
ast-grep run --lang cpp --pattern 'demo($$$ARGS)' --json=stream --custom-languages ignore path/to/example.cc
```

这里的路径是占位符，不能直接作为实际扫描目标；`--custom-languages ignore`须由该项目CLI版本
确认支持，否则停止AST步骤。输出使用调用方现有大小限制，截断时只报告已观察部分。
不使用`--rewrite`、`--update-all`、`--interactive`、`--follow`或自动安装动作。

参数语义来源为[官方ast-grep CLI参考](https://ast-grep.github.io/reference/cli/run)及
[完整CLI参考](https://ast-grep.github.io/reference/cli)；这不固定项目二进制版本，也不是执行证据。
clangd编译数据库和后台索引边界见[官方索引说明](https://clangd.llvm.org/design/indexing)和
[官方安装/编译命令说明](https://clangd.llvm.org/installation)。后台索引会产生项目缓存，
因此它属于项目所有者决定的独立动作，不随本Skill选择发生。
