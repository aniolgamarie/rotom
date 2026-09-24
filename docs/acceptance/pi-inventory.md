# Pi 盘点阶段证据

- 新增盘点/清单测试与既有CLI回归：**115 passed，17.83秒**。
- 覆盖只读源哨兵、认证文件不读取、包声明与加载证据区分、凭据URL不复制、链接拒绝、
  未知资源保留、模型字面密钥排除、重复模型不覆盖、主题提案、七角色映射、CLI与0600提案文件。
- 清单记录82项能力/资源处置，源快照记录618个Git对象条目。

执行：`.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_pi_inventory.py tests/test_pi_capability_manifest.py tests/test_cli.py`

测试均使用临时HOME与虚构资料，网络/真实子进程由fixture阻断。
由于沙箱的系统目录UID映射，文件系统回归在已批准的真实属主视图执行，未降低路径保护。

这些是只读盘点的通过证据，不证明Pi运行包、原生发现、Task Keeper或model-delegate替换已经通过。
