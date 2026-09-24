"""显式本机构建平台 helper；默认测试注入编译器替身，不运行原生宿主。"""

import hashlib
from pathlib import Path
import re
import sys
import tempfile

from .deployment import json_bytes
from .paths import configured_path
from .process import DependencyError, checked, environment
from .storage import Tree, ensure_private


def build_macos_helper(repository, output, *, run=checked, platform=None, architecture=None):
  if (platform or sys.platform) != "darwin":
    raise DependencyError("macOS helper构建需要本机SDK，不生成替代平台的通过记录")
  if architecture is not None and architecture not in ("arm64", "x86_64"): raise DependencyError("macOS helper架构不受支持")
  source = Path(repository) / "scripts/pi-supervisor-macos.c"
  with Tree(source.parent, private=False) as tree:
    raw = tree.read(source.name)
  if raw is None:
    raise DependencyError("macOS helper源码缺失")
  output = Path(output)
  ensure_private(output.parent)
  with tempfile.TemporaryDirectory(prefix=".helper-build-", dir=output.parent) as temporary:
    stage = Path(temporary)
    home = stage / "home"
    ensure_private(home)
    env = environment(home=home)
    compiler = run(["/usr/bin/clang", "--version"], cwd=stage, env=env).splitlines()[0]
    sdk_version = run(["/usr/bin/xcrun", "--show-sdk-version"], cwd=stage, env=env)
    sdk = configured_path(run(["/usr/bin/xcrun", "--show-sdk-path"], cwd=stage, env=env))
    if not re.fullmatch(r"Apple clang version [0-9.]+(?: \(clang-[A-Za-z0-9._-]+\))?", compiler) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", sdk_version):
      raise DependencyError("macOS工具链身份格式不匹配")
    with Tree(stage) as tree:
      tree.write_state("helper.c", raw[0])
    binary = stage / "helper"
    argv = ["/usr/bin/clang", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", *(["-arch", architecture] if architecture else []),
      "-isysroot", str(sdk), str(stage / "helper.c"), "-lproc", "-o", str(binary)]
    run(argv, cwd=stage, env=env)
    with Tree(stage) as tree:
      compiled = tree.read("helper")
    if compiled is None:
      raise DependencyError("编译器未生成macOS helper")
    identity = {"schema_version": 1, "compiler": compiler, "sdk_version": sdk_version,
      "source_digest": hashlib.sha256(raw[0]).hexdigest(), "helper_digest": hashlib.sha256(compiled[0]).hexdigest(), "native_verification": "not-run"}
    if architecture: identity["architecture"] = architecture
    with Tree(output.parent) as tree:
      old = tree.read(output.name)
      if old is not None:
        raise DependencyError("helper输出槽必须为空，不能覆盖运行中的组件")
      tree.replace(output.name, compiled[0], mode=0o700, expected=None)
      tree.write_immutable(output.name + ".build.json", json_bytes(identity))
  return identity


def install_platform_helpers(repository, stage, platform, *, build=None):
  if platform.startswith("linux-"): return
  if platform not in ("darwin-arm64", "darwin-x86_64"): raise DependencyError("Pi平台监督helper不受支持")
  output = Path(stage) / "bin/pi-supervisor-macos"
  (build or build_macos_helper)(repository, output, platform="darwin", architecture=platform.split("-", 1)[1])
  from .pi_assets import binary_platform
  with Tree(Path(stage)) as tree: binary = tree.read("bin/pi-supervisor-macos")
  if binary is None or not binary[1] & 0o111 or binary_platform(binary[0]) != platform:
    raise DependencyError("macOS helper构建产物架构不匹配")
