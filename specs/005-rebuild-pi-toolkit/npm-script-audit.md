# Pi npm 安装脚本静态审阅

任务：T032/T033。候选：实施基点上的未提交官方 npm 后端；固定宿主1.3.0、主题0.1.6。
解析及暂存使用 Node24.14.0/npm11.9.0、隔离临时HOME与空npm配置；未执行生命周期脚本或宿主。
119个锁定包的发布物均通过npm完整性下载。13个包声明下列生命周期；当前选择均为`ignored_not_required`。
这只是发布物与预构建入口的静态审阅，不是原生运行、账号或其他平台通过。

| 包路径/版本 | package.json SHA256 | 审阅结论 |
| --- | --- | --- |
| `node_modules/@google/genai@2.21.0` | `64e3cd991d6b4749cd4b3afe46c8a0ad2f5d983f33df94081343797693fdbc81` | preinstall仅输出no-op；prepare脚本未发布，dist/node已包含导出产物 |
| `node_modules/balanced-match@4.0.4` | `c984e6ae5c41fac085a07a732b665b22e0a26f28b61c692ba18ff458a8ecc95a` | 发布物已有运行导出产物，prepare是发布构建步骤；不安装开发构建工具 |
| `node_modules/brace-expansion@5.0.12` | `8af7dc0916002266f3b01459ef691d9f834d8ecdb0e021263280a50b913d85fa` | 发布物已有运行导出产物，prepare是发布构建步骤；不安装开发构建工具 |
| `node_modules/gaxios@7.3.1` | `6d8ac1fadd9a3e890a0407f04f49dd8b919e418e46d10e65df9cba295ce319ad` | 发布物已有运行导出产物，prepare是发布构建步骤；不安装开发构建工具 |
| `node_modules/gcp-metadata@8.1.2` | `1d50f7d982a12c539356257f1b26631ec06f569b804a596dc926ec8773224fa4` | 发布物已有运行导出产物，prepare是发布构建步骤；不安装开发构建工具 |
| `node_modules/google-auth-library@10.9.1` | `d502e0b8f9b83f97f5f78aaee9ba5e7cd7067a81d2f8f0215c47b2877814a9c9` | 发布物已有运行导出产物，prepare是发布构建步骤；不安装开发构建工具 |
| `node_modules/google-logging-utils@1.1.3` | `74980e1fd2db59c71a20ddf6accf42704c67da3b905fc5d2134ee39807dad42f` | 发布物已有运行导出产物，prepare是发布构建步骤；不安装开发构建工具 |
| `node_modules/lru-cache@11.5.3` | `c085d38560434a8915fd1817cd17cee316118078b07f40302b32ef4d8bc760f4` | 发布物已有运行导出产物，prepare是发布构建步骤；不安装开发构建工具 |
| `node_modules/minimatch@10.2.6` | `bb847ba240909c9a36d4eaeb4e0efdc3e31182aeef208c1611259a48f282ea75` | 发布物已有运行导出产物，prepare是发布构建步骤；不安装开发构建工具 |
| `node_modules/protobufjs@7.6.6` | `0e56b70de03bffc143e74311b42ae22b557370a4a1f4b5066568fbc77857639a` | postinstall源码只核对自身版本前缀并可能输出警告，不生成文件；index.js/src入口已存在 |
| `node_modules/standardwebhooks@1.1.1` | `686397f0f0202e0b693cfd3f6241d7a8da3df326f9642867a484fbbd295690b6` | 发布物已有运行导出产物，prepare是发布构建步骤；不安装开发构建工具 |
| `node_modules/undici@8.10.2` | `d3dc9b2f66b6ea0c406c8305aec87b51e7723c2f0c3c622ccd90d9d056b82464` | main index.js与lib已发布；独立build:node的undici-fetch.js不属当前主入口；prepare工具未发布 |
| `node_modules/web-streams-polyfill@3.3.3` | `13e22b076747f7673afc2afad4b932843844b1ffb2e5bd613442937eacdaf7d7` | 发布物已有运行导出产物，prepare是发布构建步骤；不安装开发构建工具 |

原始生命周期命令及精确清单摘要固定在`agents/pi/dependencies.json.script_audits`；
安装时实际清单正文或生命周期变化即拒绝激活。未知脚本不执行、也不自动加入跳过清单。
仅使用公开registry来源、已固定SHA512 SRI和实际发布物；没有修改上游。
源码或依赖升级后本结论失效，须重新审阅；不以跳过脚本宣称任何未实测功能可用。

## 可选服务的精确版本与提升路径（2026-10-19）

单选Context7与单选Brave实际解析出的npm提升路径不同；相同路径也可能分别是新版有脚本包
与旧版无脚本包。不能把250包组合的路径审计无条件复制到每种选择。

| 精确发布物 | 原始package.json SHA256 | 审阅结论 |
| --- | --- | --- |
| content-type 2.1.0 | `33102772db7c8375395bdcc11e7004c597b4cdbe457d8dd0ae2e56f5a2d28637` | prepare为`ts-scripts install && npm run build`；registry tar已含dist/index.js及MIT材料，只接受已发布产物，保持ignored_not_required |
| content-disposition 2.0.1 | `03fb6b61a5526d9b4b37bc7924734c3ddd34bf2dc70ae4d2718e501492c0b510` | 同一prepare命令，已发布dist/index.js可用；不补开发工具、不执行构建或改动vendor |

这两种审定在source catalog中同时限定`package`和`version`；解析后仅映射到实际完整锁中
精确同名同版本的路径。源catalog全量进入recipe_inputs，落位结果进入piece.script_audits；
后者继续只有原来的三个严格审计字段。旧无限定条目仍逐路径保持，不改变默认119包锁。
半对限定、未知字段、同一路径冲突及伪造锁投影都拒绝；安装阶段继续校验实际manifest原字节
摘要和完整lifecycle，不将限定当作忽略任意版本/脚本的许可。

固定源码修订后D/E分别完成lock/validate/sync/apply/doctor/重复apply，六项均exit0且
ignore-scripts；原生连接的限定通过另见[补充验收](remaining-native-acceptance.md)。
受影响依赖/publication两文件155项通过，最终完整受影响八文件324项通过；范围重叠，不累加。
