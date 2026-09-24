"""仅显式 sync 的 macOS Intel 源码构建；固定提交、私有缓存，产物不冒充原生验收。"""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import tempfile
from urllib.parse import urlsplit

from .activity import digest
from .deployment import json_bytes
from .paths import relative_path
from .pi_assets import binary_platform
from .process import DependencyError, checked
from .storage import Tree, ensure_private


def read_recipe(repository):
  with Tree(repository, private=False) as tree: raw = tree.read("agents/pi/build/readseek-source.json")
  if raw is None: raise DependencyError("ReadSeek源码构建配方缺失")
  value = json.loads(raw[0])
  if (set(value) != {"schema_version", "version", "platform", "source", "zig_version", "pdfium_builder", "submodules", "input_digests", "pdfium_dependencies"}
      or value["schema_version"] != 1 or value["version"] != "0.9.16" or value["platform"] != "darwin-x86_64"
      or value["zig_version"] != "0.16.0" or set(value["submodules"]) != {"sqlite", "zig-clap", "zigimg"}):
    raise DependencyError("ReadSeek源码构建配方无效")
  pins = [value["source"], value["pdfium_builder"], *value["submodules"].values()]
  dependencies = value["pdfium_dependencies"]
  if (set(dependencies) != {"version", "git", "files", "artifacts"} or dependencies["version"] != 1
      or "darwin-x64" not in dependencies["artifacts"]): raise DependencyError("ReadSeek PDFium依赖锁无效")
  for row in dependencies["git"]:
    if set(row) != {"path", "url", "revision"}: raise DependencyError("ReadSeek PDFium源码锁无效")
    relative_path(row["path"]); pins.append({"url": row["url"], "commit": row["revision"]})
  for row in pins:
    url = urlsplit(row.get("url", ""))
    if (set(row) != {"url", "commit"} or not re.fullmatch("[a-f0-9]{40}", row["commit"])
        or url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment):
      raise DependencyError("ReadSeek源码必须固定HTTPS提交")
  for name, sha in value["input_digests"].items():
    relative_path(name)
    if not re.fullmatch("[a-f0-9]{64}", sha): raise DependencyError("ReadSeek构建输入摘要无效")
  for row in dependencies["artifacts"]["darwin-x64"]:
    if (set(row) != {"path", "url", "sha256", "format"} or not re.fullmatch("[a-f0-9]{64}", row["sha256"])
        or not row["url"].startswith("https://") or row["format"] not in ("zip", "tar.xz")):
      raise DependencyError("ReadSeek构建工具归档未锁定")
    relative_path(row["path"])
  return value


def build_source(repository, stage, *, run=checked, host=None, which=shutil.which):
  host = host or (sys.platform, platform.machine())
  if host != ("darwin", "x86_64"): raise DependencyError("ReadSeek Intel源码构建需要本机macOS x86_64与SDK")
  recipe = read_recipe(repository)
  programs = {name: which(name) for name in ("git", "zig", "make", "python3", "patch")}
  if not all(programs.values()): raise DependencyError("ReadSeek源码构建需要Git、Zig 0.16.0、make、Python 3及patch")
  stage = Path(stage)
  with tempfile.TemporaryDirectory(prefix=".readseek-source-", dir=stage) as temporary:
    root = Path(temporary); home = root / "home"; ensure_private(home)
    env = {"HOME": str(home), "PATH": os.pathsep.join(dict.fromkeys([str(Path(path).parent) for path in programs.values()] + ["/usr/bin", "/bin"])),
      "LANG": "C.UTF-8", "TMPDIR": str(root), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_GLOBAL": "/dev/null",
      "GIT_TERMINAL_PROMPT": "0", "GIT_ATTR_NOSYSTEM": "1", "ZIG": programs["zig"], "MAKE": programs["make"],
      "ZIG_GLOBAL_CACHE_DIR": str(root / "zig-cache"), "ZIG_LOCAL_CACHE_DIR": str(root / "zig-local")}
    from .pi_vendor import installation_network
    env.update(installation_network())
    if run([programs["zig"], "version"], cwd=root, env=env) != recipe["zig_version"]: raise DependencyError("ReadSeek需要精确Zig 0.16.0")
    sdk = run(["/usr/bin/xcrun", "--show-sdk-version"], cwd=root, env=env)
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", sdk): raise DependencyError("ReadSeek macOS SDK身份无效")
    git = [programs["git"], "-c", "core.hooksPath=/dev/null", "-c", "init.templateDir=", "-c", "protocol.file.allow=never"]
    def checkout(target, pin):
      target.mkdir(parents=True, exist_ok=True)
      run([*git, "init", "--object-format=sha1", str(target)], cwd=root, env=env)
      run([*git, "-C", str(target), "fetch", "--depth=1", pin["url"], pin["commit"]], cwd=root, env=env)
      run([*git, "-C", str(target), "checkout", "--detach", pin["commit"]], cwd=root, env=env)
      if run([*git, "-C", str(target), "rev-parse", "HEAD"], cwd=root, env=env) != pin["commit"]: raise DependencyError("ReadSeek源码提交不匹配")
    source = root / "source"; checkout(source, recipe["source"])
    with Tree(source, private=False) as tree:
      for name, expected in recipe["input_digests"].items():
        raw = tree.read(name, max_bytes=1024 * 1024)
        if raw is None or hashlib.sha256(raw[0]).hexdigest() != expected: raise DependencyError("ReadSeek源码构建输入不匹配")
      locked = json.loads(tree.read("packages/readseek/scripts/pdfium-deps.lock")[0])
      if locked != recipe["pdfium_dependencies"]: raise DependencyError("ReadSeek PDFium锁不匹配")
    package = source / "packages/readseek"
    for name, pin in recipe["submodules"].items():
      tracked = run([*git, "-C", str(source), "ls-files", "--stage", "--", "packages/readseek/libs/" + name], cwd=root, env=env)
      if not tracked.startswith("160000 " + pin["commit"] + " "): raise DependencyError("ReadSeek子模块提交不匹配")
      checkout(package / "libs" / name, pin)
    builder = root / "pdfium-builder"; checkout(builder, recipe["pdfium_builder"])
    env["PDFIUM_BUILDER_DIR"] = str(builder)
    # 上游固定脚本验证PDFium的每个Git提交与工具归档摘要；缓存都位于本次构建目录。
    for name in ("build-sqlite.sh", "build-pdfium.sh"):
      run(["/bin/bash", str(package / "scripts" / name)], cwd=package, env=env)
    run([programs["zig"], "build", "-Doptimize=ReleaseFast", "--prefix", str(root / "output")], cwd=package, env=env)
    with Tree(root / "output", private=False) as tree: binary = tree.read("bin/readseek", max_bytes=128 * 1024 * 1024)
    if binary is None or not binary[1] & 0o111 or binary_platform(binary[0]) != "darwin-x86_64": raise DependencyError("ReadSeek源码产物架构或入口无效")
    repositories = [source, *(package / "libs" / name for name in recipe["submodules"]), builder,
      *(builder / row["path"] for row in recipe["pdfium_dependencies"]["git"])]
    licenses = {}
    for index, directory in enumerate(repositories):
      names = run([*git, "-C", str(directory), "ls-files", "-z"], cwd=root, env=env).split("\0")
      with Tree(directory, private=False) as tree:
        for name in names:
          if not name or not re.match(r"(?i)^(license|copying|notice|authors)(?:$|[._-])", Path(name).name): continue
          raw = tree.read(name, max_bytes=2 * 1024 * 1024)
          if raw is not None: licenses[f"licenses/readseek-source/{index}/{name}"] = raw[0]
    if not licenses: raise DependencyError("ReadSeek源码构建许可证缺失")
    receipt = {"schema_version": 1, "version": recipe["version"], "platform": recipe["platform"], "source_commit": recipe["source"]["commit"],
      "recipe_digest": digest(recipe), "zig_version": recipe["zig_version"], "sdk_version": sdk, "entrypoint": "bin/readseek",
      "binary_sha256": hashlib.sha256(binary[0]).hexdigest(), "license_digests": {name: hashlib.sha256(raw).hexdigest() for name, raw in licenses.items()},
      "native_verification": "not-run"}
    with Tree(stage) as tree:
      tree.replace("bin/readseek", binary[0], mode=0o700, expected=None)
      for name, raw in licenses.items(): tree.write_new(name, raw)
      tree.write_new("runtime/readseek-native.json", json_bytes(receipt))
    return receipt
