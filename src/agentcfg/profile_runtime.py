"""包拥有的固定 DSH profile；只选择已安装运行包，不调用原生安装器。"""

import json
import os
import uuid

from .deployment import json_bytes
from .storage import Conflict, Tree, ensure_private


def prepare(workspace, runtime):
  """调用者持实例锁。原生 cordis.yml/会话保持运行时拥有，不参与配置回滚。"""
  profile = workspace.instance / "dsh-home/profiles/agentcfg"
  ensure_private(profile)
  manifest = {"name": "agentcfg-managed-profile", "version": "1.0.0", "private": True,
    "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base", "@deepseek-harness-tui/dsh-tui"]}}}
  with Tree(profile) as tree:
    owner = tree.read(".agentcfg-package-owner.json")
    package = tree.read("package.json")
    if owner is None and package is not None:
      raise Conflict("原生 profile 存在未接管的 package.json")
    record = json.loads(owner[0]) if owner else {"runtime": None, "binding": workspace.binding}
    if record["binding"] != workspace.binding:
      raise Conflict("原生 profile 属于另一份机器配置")
    expected_package = json_bytes(manifest)
    if package is not None and package[0] != expected_package:
      raise Conflict("包拥有的 profile 配置已被修改")
    if package is None:
      tree.write_state("package.json", expected_package)
    destination = str(runtime / "node_modules")
    with tree.parent("node_modules") as (fd, name):
      try:
        old = os.readlink(name, dir_fd=fd)
      except FileNotFoundError:
        old = None
      except OSError:
        raise Conflict("原生 profile node_modules 不是已知运行包链接") from None
      if old is not None and old not in (record["runtime"], destination):
        raise Conflict("原生 profile 运行包链接已被外部修改")
      if old != destination:
        temporary = ".agentcfg-modules-" + uuid.uuid4().hex
        os.symlink(destination, temporary, dir_fd=fd)
        try:
          os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        finally:
          try:
            os.unlink(temporary, dir_fd=fd)
          except FileNotFoundError:
            pass
        os.fsync(fd)
    tree.write_state(".agentcfg-package-owner.json", json_bytes({"binding": workspace.binding, "runtime": destination}))
  return profile
