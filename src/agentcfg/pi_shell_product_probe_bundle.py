"""静态合成产品Shell探针包；只复制显式来源，不运行进程或启用产品factory。

runtime身份只标识本探针输入，不是正式lock/candidate。收据不摘要自身，由外层清单绑定。
包内清单不构成独立授权；preflight还从当前声明、固定模板与来源重新核验。
controllers保守绑定静态本地Python导入闭包，不是Base加载或复制集合。
"""

import ast
import json
import os
from pathlib import Path
import re
import stat
import uuid

from .activity import digest
from .deployment import json_bytes
from .paths import _absolute_directory
from .pi_shell_probe import ROOT, FIXTURE, BOOTSTRAP, PYTHON, CANARIES, sources, dependencies, file_identity, sha
from .pi_runtime_files import install_files, validate_files, verify_sources
from .schema import ConfigError
from .storage import Tree


CASES = ("allowed", "denied", "background")
PROBE_ID = "shell-product-linux-x86_64-v1"
LOCK_IDENTITY = digest({"synthetic": "shell-product-probe-lock-v1"})
SLICE_IDENTITY = digest({"synthetic": "shell-product-probe-slice-v1"})
HEAD = b"ref: refs/heads/fixture\n"
CONTROLLERS = ("src/agentcfg/pi_shell_product_probe_bundle.py", "src/agentcfg/pi_shell_product_probe.py", "scripts/pi-probe-shell-product.py")
CONTROLLER_DATA = ("agents/pi/schemas/options.schema.json",)
FIELDS = {"schema_version", "probe_id", "cases", "source_rows", "runtime_identity", "helper_identity",
  "lock_identity", "slice_identity", "nonces", "system", "files", "directories", "controllers"}
MAX_FILES = 10000
MAX_FILE_BYTES = 16 * 1024 * 1024


def _require(value):
  if not value: raise ConfigError("pi-shell-product-probe-bundle")


def _hex(value, count=64):
  _require(type(value) is str and re.fullmatch("[0-9a-f]{" + str(count) + "}", value) is not None)


def _absolute(value):
  path = Path(value)
  _require(path.is_absolute() and ".." not in path.parts and str(path) != "/")
  return path


def _directory(value):
  path = _absolute(value)
  _require(path != Path("/tmp") and path.is_relative_to("/tmp"))
  return path


def _pairs(items):
  value = {}
  for key, item in items:
    _require(key not in value); value[key] = item
  return value


def _decode(raw):
  def invalid(value): raise ConfigError("pi-shell-product-probe-bundle")
  return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs, parse_constant=invalid)


def _system():
  return {"bootstrap": file_identity(BOOTSTRAP), "python": file_identity(PYTHON),
    "bash": file_identity(Path("/usr/bin/bash")), "dependencies": dependencies()}


def _source_path(name):
  _require(type(name) is str and re.fullmatch(r"(?:src/agentcfg/[a-z_][a-z0-9_]*\.py|scripts/pi-[a-z-]+\.py)", name))
  return name


def _module_path(name):
  _require(type(name) is str and re.fullmatch(r"[a-z_][a-z0-9_]*", name))
  return "src/agentcfg/" + name + ".py"


def _controllers():
  # ast.walk含函数内/未选择分支；只读源码，不导入或扫描无关目录。
  pending = {*(_source_path(name) for name in CONTROLLERS), "src/agentcfg/__init__.py"}
  result = {}
  with Tree(ROOT, private=False) as source:
    def read(name):
      before = file_identity(ROOT / name)
      raw = source.read(name, max_bytes=MAX_FILE_BYTES)
      _require(raw is not None)
      after = file_identity(ROOT / name)
      _require(before == after and before["sha256"] == sha(raw[0]))
      result[name] = sha(raw[0])
      return raw[0]
    while pending:
      _require(len(result) + len(pending) <= 2048)
      name = min(pending); pending.remove(name)
      if name in result: continue
      syntax = ast.parse(read(name), filename=name)
      for node in ast.walk(syntax):
        modules = []
        if isinstance(node, ast.ImportFrom):
          if node.level:
            _require(name.startswith("src/agentcfg/") and node.level == 1)
            modules = [node.module] if node.module else [alias.name for alias in node.names]
          elif node.module == "agentcfg": modules = [alias.name for alias in node.names]
          elif node.module and node.module.startswith("agentcfg."): modules = [node.module.removeprefix("agentcfg.")]
        elif isinstance(node, ast.Import):
          modules = [alias.name.removeprefix("agentcfg.") for alias in node.names if alias.name.startswith("agentcfg.")]
        for module in modules:
          target = _module_path(module)
          if target not in result: pending.add(target)
    for name in CONTROLLER_DATA:
      _require(type(name) is str and re.fullmatch(r"agents/pi/schemas/[a-z0-9_-]+\.schema\.json", name))
      _require(name not in result); read(name)
  return dict(sorted(result.items()))


def _runtime_identity(binary, rows):
  return digest({"probe_id": PROBE_ID, "helper_identity": sha(binary), "source_rows": rows})


def _templates():
  with Tree(FIXTURE, private=False) as source:
    result = {}
    for name in ("payload.py", "heartbeat.py"):
      item = source.read(name, max_bytes=MAX_FILE_BYTES)
      _require(item is not None); result[name] = item[0]
    return result


def _generated(runtime_identity, binary, rows):
  profile = json_bytes({"schema_version": 2, "profile_id": "pi-base", "runtime_identity": runtime_identity,
    "lock_identity": LOCK_IDENTITY, "slice_identity": SLICE_IDENTITY})
  commands = json_bytes({"schema_version": 1, "programs": {"ordinary-shell": {
    "entrypoint": "supervisor/scripts/pi-shell.py", "kind": "external", "engine": "python"}}})
  content = {"bin/pi-bwrap": binary, "runtime/profile.json": profile, "runtime/commands.json": commands}
  files = {row["path"]: {"kind": "file", "mode": row["mode"], "sha256": row["digest"]} for row in rows}
  files.update({name: {"kind": "file", "mode": 0o700 if name == "bin/pi-bwrap" else 0o600,
    "sha256": sha(data)} for name, data in content.items()})
  content[".agentcfg-receipt.json"] = json_bytes({"schema_version": 2, "identity": runtime_identity,
    "lock_identity": LOCK_IDENTITY, "slice_identity": SLICE_IDENTITY, "files": files})
  return content


def _layout(runtime_identity, rows):
  prefix = "inputs/" + runtime_identity + "/"
  files = {prefix + row["path"] for row in rows}
  files.update(prefix + name for name in ("bin/pi-bwrap", "runtime/profile.json", "runtime/commands.json", ".agentcfg-receipt.json"))
  empty = set()
  for case in CASES:
    case_root = "cases/" + case + "/"
    work = case_root + "work/"
    files.update(work + name for name in CANARIES)
    files.update(work + "readonly/" + name for name in ("payload.py", "heartbeat.py"))
    files.add(work + "project/.git/HEAD")
    empty.update(case_root + name for name in ("state", "instance", "private-account-home", "observations", "work/home"))
  directories = {parent.as_posix() for name in files | empty for parent in Path(name).parents if parent != Path(".")} | empty
  return files, directories


def inventory(directory):
  """固定包的无链接清单；plan自身单独核验，不纳入自身摘要。"""
  root = _directory(directory)
  root_info = root.lstat()
  _require(stat.S_ISDIR(root_info.st_mode) and stat.S_IMODE(root_info.st_mode) == 0o700 and root_info.st_uid == os.geteuid())
  files, directories = {}, []
  count = 0
  with Tree(root) as tree:
    def walk(path, depth=0):
      nonlocal count
      _require(depth <= 64)
      for entry in os.scandir(path):
        count += 1; _require(count <= MAX_FILES)
        name = Path(entry.path).relative_to(root).as_posix()
        info = entry.stat(follow_symlinks=False)
        _require(info.st_uid == os.geteuid())
        if stat.S_ISDIR(info.st_mode):
          _require(stat.S_IMODE(info.st_mode) == 0o700)
          directories.append(name); walk(Path(entry.path), depth + 1)
        else:
          _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
          mode = stat.S_IMODE(info.st_mode)
          _require(mode in (0o600, 0o700))
          if name == "plan.json":
            _require(mode == 0o600); continue
          raw = tree.read(name, max_bytes=MAX_FILE_BYTES)
          _require(raw is not None)
          files[name] = {"sha256": sha(raw[0]), "mode": mode}
    walk(root)
  return files, sorted(directories)


def _validate_plan(plan):
  _require(type(plan) is dict and set(plan) == FIELDS)
  _require(type(plan["schema_version"]) is int and plan["schema_version"] == 1
    and plan["probe_id"] == PROBE_ID and type(plan["cases"]) is list and plan["cases"] == list(CASES))
  for key in ("runtime_identity", "helper_identity", "lock_identity", "slice_identity"): _hex(plan[key])
  _require(type(plan["nonces"]) is dict and set(plan["nonces"]) == set(CASES))
  for nonce in plan["nonces"].values(): _hex(nonce, 32)
  _require(len(set(plan["nonces"].values())) == len(CASES))
  _require(type(plan["source_rows"]) is list and 0 < len(plan["source_rows"]) <= 2048)
  _require(type(plan["system"]) is dict and set(plan["system"]) == {"bootstrap", "python", "bash", "dependencies"})
  for key, value in plan["system"].items():
    _require(type(value) is dict and set(value) == ({"path", "device", "inode"} if key == "dependencies" else {"path", "sha256", "device", "inode"}))
    _require(type(value["path"]) is str and str(_absolute(value["path"])) == value["path"])
    for field in ("device", "inode"): _require(type(value[field]) is int and value[field] >= 0)
    if key != "dependencies": _hex(value["sha256"])
  _require(type(plan["controllers"]) is dict and 0 < len(plan["controllers"]) <= 2048)
  for name in plan["controllers"]:
    if name not in CONTROLLER_DATA: _source_path(name)
  for value in plan["controllers"].values(): _hex(value)
  _require(type(plan["files"]) is dict and 0 < len(plan["files"]) <= MAX_FILES)
  for name, info in plan["files"].items():
    _require(type(name) is str and type(info) is dict and set(info) == {"sha256", "mode"})
    _hex(info["sha256"])
    _require(type(info["mode"]) is int and info["mode"] in (0o600, 0o700))
  _require(type(plan["directories"]) is list and len(plan["directories"]) <= MAX_FILES
    and all(type(name) is str for name in plan["directories"])
    and plan["directories"] == sorted(set(plan["directories"])))


def _prepare(directory):
  directory = _directory(directory); _require(not os.path.lexists(directory))
  binary, rows = sources()
  verify_sources(ROOT, rows)
  _require(all(row["path"].startswith("supervisor/") for row in rows))
  runtime_identity = _runtime_identity(binary, rows)
  system, controllers, templates = _system(), _controllers(), _templates()
  with _absolute_directory(directory.parent) as parent: os.mkdir(directory.name, 0o700, dir_fd=parent)
  runtime = directory / "inputs" / runtime_identity
  with Tree(directory) as tree:
    with tree.parent("inputs/" + runtime_identity + "/.unused", create=True): pass
  install_files(ROOT, runtime, rows)
  with Tree(runtime) as tree:
    for name, data in _generated(runtime_identity, binary, rows).items(): tree.write_new(name, data)
    with tree.parent("bin/pi-bwrap") as (parent, name):
      fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
      try: os.fchmod(fd, 0o700)
      finally: os.close(fd)
  validate_files(runtime, rows)
  with Tree(directory) as tree:
    for case in CASES:
      prefix = "cases/" + case + "/"
      for name, data in CANARIES.items(): tree.write_new(prefix + "work/" + name, data)
      tree.write_new(prefix + "work/project/.git/HEAD", HEAD)
      for name, data in templates.items(): tree.write_new(prefix + "work/readonly/" + name, data)
      for name in ("state", "instance", "private-account-home", "observations", "work/home"):
        with tree.parent(prefix + name + "/.unused", create=True): pass
  files, dirs = inventory(directory)
  expected_files, expected_dirs = _layout(runtime_identity, rows)
  _require(set(files) == expected_files and set(dirs) == expected_dirs)
  plan = {"schema_version": 1, "probe_id": PROBE_ID, "cases": list(CASES), "source_rows": rows,
    "runtime_identity": runtime_identity, "helper_identity": sha(binary), "lock_identity": LOCK_IDENTITY,
    "slice_identity": SLICE_IDENTITY, "nonces": {case: uuid.uuid4().hex for case in CASES},
    "system": system, "files": files, "directories": dirs, "controllers": controllers}
  _validate_plan(plan)
  with Tree(directory) as tree: tree.write_new("plan.json", json_bytes(plan))
  return plan


def prepare(directory):
  try: return _prepare(directory)
  except Exception: raise ConfigError("pi-shell-product-probe-bundle") from None


def _preflight(directory):
  directory = _directory(directory)
  _require(not os.path.lexists(directory / "execution-started.json"))
  with Tree(directory) as tree:
    item = tree.read("plan.json", max_bytes=4 * 1024 * 1024)
    _require(item is not None and item[1] == 0o600); plan = _decode(item[0])
  _validate_plan(plan)
  binary, rows = sources(); verify_sources(ROOT, rows)
  _require(plan["source_rows"] == rows and plan["helper_identity"] == sha(binary)
    and plan["runtime_identity"] == _runtime_identity(binary, rows)
    and plan["lock_identity"] == LOCK_IDENTITY and plan["slice_identity"] == SLICE_IDENTITY)
  _require(plan["system"] == _system() and plan["controllers"] == _controllers())
  files, dirs = inventory(directory)
  expected_files, expected_dirs = _layout(plan["runtime_identity"], rows)
  _require(set(files) == expected_files and set(dirs) == expected_dirs and files == plan["files"] and dirs == plan["directories"])
  runtime = directory / "inputs" / plan["runtime_identity"]
  validate_files(runtime, rows)
  with Tree(runtime) as tree:
    for name, data in _generated(plan["runtime_identity"], binary, rows).items():
      item = tree.read(name, max_bytes=MAX_FILE_BYTES)
      _require(item is not None and item[0] == data and item[1] == (0o700 if name == "bin/pi-bwrap" else 0o600))
  templates = _templates()
  with Tree(directory) as tree:
    for case in CASES:
      prefix = "cases/" + case + "/work/"
      fixed = {**CANARIES, "project/.git/HEAD": HEAD,
        **{"readonly/" + name: data for name, data in templates.items()}}
      for name, data in fixed.items():
        item = tree.read(prefix + name, max_bytes=MAX_FILE_BYTES)
        _require(item is not None and item[0] == data and item[1] == 0o600)
  return plan


def preflight(directory):
  try: return _preflight(directory)
  except Exception: raise ConfigError("pi-shell-product-probe-bundle") from None
