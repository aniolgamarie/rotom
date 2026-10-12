"""有限 wheel 的纯数据编译；一致性数据不授予安装、来源或加载资格。"""

import base64
import copy
import csv
import hashlib
import io
import json
import re
import struct
import zlib


_CAPS = {
  "archive_bytes": 2097152, "archive_set_bytes": 8388608,
  "member_expanded_bytes": 16777216, "wheel_expanded_bytes": 67108864,
  "wheel_entries": 20000, "compression_ratio": 200, "set_entries": 4096,
  "set_expanded_bytes": 16777216, "metadata_member_bytes": 1048576,
  "metadata_wheel_total_bytes": 2097152, "archive_member_path_bytes": 512,
  "target_path_bytes": 1024, "name_bytes": 128, "version_bytes": 64,
  "wheel_filename_bytes": 256, "source_id_bytes": 96,
  "requirement_raw_bytes": 512, "requires_dist_per_wheel": 64,
  "requires_dist_set": 256, "license_files_per_wheel": 16,
  "occupied_files": 16384, "canonical_declaration_bytes": 8388608,
  "canonical_plan_or_inventory_bytes": 16777216, "data_depth": 16,
  "data_nodes": 100000, "planned_directories": 16384,
  "path_components": 64, "header_lines": 2048, "header_line_bytes": 4096,
}
_NAMES = ["attrs", "jsonschema", "jsonschema-specifications", "pyyaml", "referencing", "rpds-py", "typing-extensions"]
_ROOTS = {
  "attrs": ("attr", "attrs"), "jsonschema": ("jsonschema",),
  "jsonschema-specifications": ("jsonschema_specifications",),
  "pyyaml": ("_yaml", "yaml"), "referencing": ("referencing",),
  "rpds-py": ("rpds",), "typing-extensions": ("typing_extensions.py",),
}
_PLATFORMS = ["manylinux2014_x86_64", "manylinux_2_17_x86_64", "manylinux_2_28_x86_64"]
_FIXED = {
  "schema_version": 1, "layout": "flat-wheel-subset-v1", "profile_id": "pi-full",
  "library_root": "supervisor/python-bundle/site-packages",
  "inventory_path": "supervisor/python-bundle/inventory.json",
  "file_mode": 384, "directory_mode": 448,
}
_PARENT = "supervisor/python-bundle"
_ENTRY_TEXT = "[console_scripts]\njsonschema = jsonschema.cli:main\n"
_DECL = set(_FIXED) | {"roots", "extras", "target", "wheels"}
_ROW = set("source_id name version wheel_filename archive_size archive_sha256 dist_info metadata wheel entry_points members explicit_directories".split())
_META = set("metadata_version name version requires_python requires_dist provides_extra license_expression legacy_license license_files".split())
_WHEEL = set("wheel_version root_is_purelib tags build".split())
_MEMBER = {"path", "size", "sha256", "role"}
_TARGET = set("implementation python_release abi sys_platform machine platform_tags".split())
_ENCODER = json.JSONEncoder(sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _fail():
  raise ValueError()


def _boundary(function, *args):
  failed = False
  try:
    result = function(*args)
  except Exception:
    failed = True
  if failed:
    # 仅清理新错误，保留调用方原异常；裸重抛也清理外层活跃上下文。
    try:
      raise ValueError("pi-python-bundle")
    except ValueError as error:
      error.__cause__ = None
      error.__context__ = None
      raise
  return result


def validate_python_bundle_declaration(declaration):
  """核声明及有限图；不读取档案，不签发权限。"""
  _boundary(_declaration, declaration)


def plan_python_bundle_install(declaration, artifact_bytes, *, occupied_files):
  """核完整档案字节并返回无 payload 的 detached JSON 计划。"""
  return _boundary(_plan, declaration, artifact_bytes, occupied_files)


def validate_python_bundle_inventory(declaration, inventory):
  """核 claimed inventory 与声明一致；不证明物理 readback。"""
  _boundary(_inventory, declaration, inventory)


def _native(value):
  nodes = 0
  active = set()
  def walk(item, depth):
    nonlocal nodes
    nodes += 1
    if nodes > _CAPS["data_nodes"] or depth > _CAPS["data_depth"]:
      _fail()
    kind = type(item)
    if kind is str:
      # 所有本契约字符串均更短；先限字符数，避免编码外来大对象。
      if len(item) > 4096:
        _fail()
      item.encode("utf-8", "strict")
    elif kind in (dict, list):
      if id(item) in active or len(item) > _CAPS["data_nodes"]:
        _fail()
      active.add(id(item))
      if kind is dict:
        for key, child in item.items():
          if type(key) is not str:
            _fail()
          walk(key, depth + 1)
          walk(child, depth + 1)
      else:
        for child in item:
          walk(child, depth + 1)
      active.remove(id(item))
    elif kind is int:
      if not -(2 ** 63) <= item <= 2 ** 63 - 1:
        _fail()
    elif kind not in (bool, type(None)):
      _fail()
  walk(value, 0)
  return nodes


def _canonical(value, cap):
  parts = []
  size = 0
  for part in _ENCODER.iterencode(value):
    encoded = part.encode("utf-8")
    size += len(encoded)
    if size > cap:
      _fail()
    parts.append(encoded)
  return b"".join(parts)


def _digest(value, cap):
  return hashlib.sha256(_canonical(value, cap)).hexdigest()


def _shape(value, fields):
  if type(value) is not dict or set(value) != fields:
    _fail()


def _integer(value, minimum, maximum):
  if type(value) is not int or not minimum <= value <= maximum:
    _fail()


def _string(value, cap, *, ascii_only=False):
  if type(value) is not str or not value or len(value.encode("utf-8")) > cap:
    _fail()
  if any(ord(char) < 32 or ord(char) == 127 for char in value):
    _fail()
  if ascii_only and not value.isascii():
    _fail()


def _list(value, maximum, *, minimum=0, sorted_unique=False, unique=False):
  if type(value) is not list or not minimum <= len(value) <= maximum:
    _fail()
  if sorted_unique and value != sorted(set(value)):
    _fail()
  if unique and len(value) != len(set(value)):
    _fail()


def _hash(value):
  if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
    _fail()


def _name(value):
  _string(value, _CAPS["name_bytes"], ascii_only=True)
  if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", value):
    _fail()
  return re.sub(r"[-_.]+", "-", value).lower()


def _release(value, canonical=False):
  _string(value, _CAPS["version_bytes"], ascii_only=True)
  if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", value):
    _fail()
  parts = value.split(".")
  result = []
  for part in parts:
    if len(part) > 8 or (canonical and part != str(int(part))):
      _fail()
    result.append(int(part))
  return result


def _tuple(release):
  return tuple(release + [0] * (3 - len(release)))


def _path(path, cap=512):
  _string(path, cap, ascii_only=True)
  parts = path.split("/")
  if len(parts) > _CAPS["path_components"]:
    _fail()
  for part in parts:
    low = part.lower()
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+", part) or part in (".", "..")
        or low.endswith((".data", ".pth", ".pyc", ".pyo"))
        or low == "__pycache__" or low.split(".")[0] in ("sitecustomize", "usercustomize")):
      _fail()
  return parts


def _member_path(row, path, directory=False):
  parts = _path(path, _CAPS["archive_member_path_bytes"])
  if parts[0] not in (*_ROOTS[row["name"]], row["dist_info"]):
    _fail()
  if parts[0] == "typing_extensions.py" and (directory or len(parts) != 1):
    _fail()
  if path in (row["dist_info"] + "/RECORD.jws", row["dist_info"] + "/RECORD.p7s"):
    _fail()


def _role(row, path):
  if path.startswith(row["dist_info"] + "/licenses/"):
    return "license"
  if path.startswith(row["dist_info"] + "/"):
    return "metadata"
  if path.endswith(".so"):
    return "native"
  if path.endswith((".py", ".pyi")):
    return "python"
  return "resource"


def _parents(path):
  parts = path.split("/")
  for index in range(1, len(parts)):
    yield "/".join(parts[:index])


def _file_set(paths):
  # 逐级 parent 集合检查，避免两集合逐对乘积。
  seen = set()
  for path in paths:
    folded = path.casefold()
    if folded in seen:
      _fail()
    seen.add(folded)
  for path in seen:
    if any(parent in seen for parent in _parents(path)):
      _fail()
  return seen


def _target(target):
  _shape(target, _TARGET)
  for key, value in {"implementation": "cpython", "abi": "cp311", "sys_platform": "linux", "machine": "x86_64"}.items():
    if target[key] != value:
      _fail()
  release = target["python_release"]
  _list(release, 3, minimum=3)
  for part in release:
    _integer(part, 0, 999999)
  if release[:2] != [3, 11]:
    _fail()
  tags = target["platform_tags"]
  _list(tags, 3, minimum=1, sorted_unique=True)
  if not set(tags) <= set(_PLATFORMS):
    _fail()


def _tags(row, target):
  wheel = row["wheel"]
  _shape(wheel, _WHEEL)
  if wheel["wheel_version"] != "1.0" or wheel["root_is_purelib"] not in ("true", "false") or wheel["build"] is not None:
    _fail()
  _list(wheel["tags"], 4, minimum=1, unique=True)
  allowed = {"py3-none-any"} | {"cp311-cp311-" + tag for tag in _PLATFORMS}
  if not set(wheel["tags"]) <= allowed:
    _fail()
  compatible = {"py3-none-any"} | {"cp311-cp311-" + tag for tag in target["platform_tags"]}
  if not set(wheel["tags"]) & compatible:
    _fail()
  filename = row["wheel_filename"]
  _string(filename, _CAPS["wheel_filename_bytes"], ascii_only=True)
  match = re.fullmatch(r"([A-Za-z0-9_]+)-([0-9.]+)-([A-Za-z0-9_.]+)-([A-Za-z0-9_.]+)-([A-Za-z0-9_.]+)\.whl", filename)
  if not match or _name(match[1]) != row["name"] or match[2] != row["version"]:
    _fail()
  alternatives = [component.split(".") for component in match.groups()[2:]]
  if any(len(group) != len(set(group)) for group in alternatives):
    _fail()
  expanded = {py + "-" + abi + "-" + platform for py in alternatives[0] for abi in alternatives[1] for platform in alternatives[2]}
  if expanded != set(wheel["tags"]):
    _fail()


def _metadata(row):
  metadata = row["metadata"]
  _shape(metadata, _META)
  if metadata["metadata_version"] != "2.4" or _name(metadata["name"]) != row["name"] or metadata["version"] != row["version"]:
    _fail()
  _string(metadata["requires_python"], _CAPS["version_bytes"], ascii_only=True)
  requirements = metadata["requires_dist"]
  _list(requirements, _CAPS["requires_dist_per_wheel"])
  for raw in requirements:
    _string(raw, _CAPS["requirement_raw_bytes"], ascii_only=True)
  extras = metadata["provides_extra"]
  _list(extras, 2, unique=True)
  if extras != (["format", "format-nongpl"] if row["name"] == "jsonschema" else []):
    _fail()
  for field in ("license_expression", "legacy_license"):
    if metadata[field] is not None:
      _string(metadata[field], 256)
  if metadata["license_expression"] is not None and metadata["legacy_license"] is not None:
    _fail()
  licenses = metadata["license_files"]
  _list(licenses, _CAPS["license_files_per_wheel"], minimum=1, unique=True)
  for path in licenses:
    _path(path, _CAPS["archive_member_path_bytes"])
  entry = row["entry_points"]
  if entry is not None:
    _shape(entry, {"member", "text"})
    if row["name"] != "jsonschema" or entry != {"member": row["dist_info"] + "/entry_points.txt", "text": _ENTRY_TEXT}:
      _fail()


def _rules(declaration):
  rows = {row["name"]: row for row in declaration["wheels"]}
  requirements, python = [], []
  for row in declaration["wheels"]:
    raw = row["metadata"]["requires_python"]
    match = re.fullmatch(r">=([0-9]+(?:\.[0-9]+){0,2})", raw)
    if not match:
      _fail()
    release = _release(match[1])
    if _tuple(declaration["target"]["python_release"]) < _tuple(release):
      _fail()
    python.append({"source_id": row["source_id"], "raw": raw, "operator": ">=", "raw_release": match[1], "release": release, "satisfied": True})
    for ordinal, raw in enumerate(row["metadata"]["requires_dist"]):
      match = re.fullmatch(r"([A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*)(?:(>=|>)([0-9]+(?:\.[0-9]+){0,2}))?(?:; (extra == '(?:format|format-nongpl)'|python_version < '3\.13'))?", raw)
      if not match:
        _fail()
      name, operator, raw_release, marker_raw = match.groups()
      name = _name(name)
      release = _release(raw_release) if raw_release is not None else None
      marker = None
      active = True
      if marker_raw:
        variable, marker_operator, quoted = marker_raw.split(" ")
        value = quoted[1:-1]
        marker = {"variable": variable, "operator": marker_operator, "value": value}
        if variable == "extra":
          if value not in row["metadata"]["provides_extra"]:
            _fail()
          active = False
        else:
          active = declaration["target"]["python_release"][:2] < [3, 13]
      selected = rows[name]["version"] if active and name in rows else None
      if active:
        if selected is None:
          _fail()
        if release is not None:
          actual, bound = _tuple(_release(selected, True)), _tuple(release)
          if not (actual >= bound if operator == ">=" else actual > bound):
            _fail()
      requirements.append({"source_id": row["source_id"], "ordinal": ordinal, "raw": raw, "name": name, "operator": operator,
                           "raw_release": raw_release, "release": release, "marker": marker, "active": active,
                           "selected_version": selected, "satisfied": True if active else None})
  return requirements, python


def _declaration(declaration):
  _native(declaration)
  _shape(declaration, _DECL)
  for key, value in _FIXED.items():
    if type(declaration[key]) is not type(value) or declaration[key] != value:
      _fail()
  if declaration["roots"] != ["jsonschema", "pyyaml"] or declaration["extras"] != []:
    _fail()
  _target(declaration["target"])
  _list(declaration["wheels"], 7, minimum=7)
  if [row["name"] for row in declaration["wheels"]] != _NAMES:
    _fail()
  raw_total = expanded_total = entries_total = requirements_total = 0
  all_files, all_dirs = [], []
  for row in declaration["wheels"]:
    _shape(row, _ROW)
    _release(row["version"], True)
    if row["source_id"] != "durable-python-" + row["name"]:
      _fail()
    _string(row["source_id"], _CAPS["source_id_bytes"], ascii_only=True)
    if row["dist_info"] != row["name"].replace("-", "_") + "-" + row["version"] + ".dist-info":
      _fail()
    _integer(row["archive_size"], 1, _CAPS["archive_bytes"])
    _hash(row["archive_sha256"])
    _tags(row, declaration["target"])
    _metadata(row)
    _list(row["members"], _CAPS["set_entries"], minimum=1)
    paths = []
    expanded = metadata_total = 0
    for member in row["members"]:
      _shape(member, _MEMBER)
      _member_path(row, member["path"])
      _integer(member["size"], 0, _CAPS["member_expanded_bytes"])
      _hash(member["sha256"])
      if member["role"] != _role(row, member["path"]):
        _fail()
      paths.append(member["path"])
      expanded += member["size"]
      if member["role"] == "metadata":
        _integer(member["size"], 0, _CAPS["metadata_member_bytes"])
        metadata_total += member["size"]
    if paths != sorted(set(paths)) or expanded > _CAPS["wheel_expanded_bytes"] or metadata_total > _CAPS["metadata_wheel_total_bytes"]:
      _fail()
    directories = row["explicit_directories"]
    _list(directories, _CAPS["set_entries"], sorted_unique=True)
    for path in directories:
      _member_path(row, path, True)
    required = {row["dist_info"] + "/" + name for name in ("METADATA", "WHEEL", "RECORD")}
    required.update(row["dist_info"] + "/licenses/" + path for path in row["metadata"]["license_files"])
    entry_path = row["dist_info"] + "/entry_points.txt"
    if row["entry_points"] is not None:
      required.add(entry_path)
    elif entry_path in paths:
      _fail()
    if not required <= set(paths):
      _fail()
    entries = len(paths) + len(directories)
    if entries > _CAPS["wheel_entries"]:
      _fail()
    all_files.extend(paths)
    all_dirs.extend(directories)
    raw_total += row["archive_size"]
    expanded_total += expanded
    entries_total += entries
    requirements_total += len(row["metadata"]["requires_dist"])
    if (raw_total > _CAPS["archive_set_bytes"] or expanded_total > _CAPS["set_expanded_bytes"]
        or entries_total > _CAPS["set_entries"] or requirements_total > _CAPS["requires_dist_set"]):
      _fail()
  files = _file_set(all_files)
  # 目录允许共享，但拼写不一致及文件阻塞不允许。
  directories = {}
  for path in all_dirs:
    folded = path.casefold()
    if folded in directories and directories[folded] != path:
      _fail()
    directories[folded] = path
    if folded in files or any(parent in files for parent in _parents(folded)):
      _fail()
  _canonical(declaration, _CAPS["canonical_declaration_bytes"])
  _rules(declaration)
  # 同时核由隐式目录产生的大小写和对象/目录上限。
  _compile(declaration)


class _Budget:
  """在添加记录之前限制最终 JSON 对象与 canonical 大小。"""
  def __init__(self, initial):
    self.nodes = _native(initial)
    self.size = len(_canonical(initial, _CAPS["canonical_plan_or_inventory_bytes"]))

  def reserve(self, nodes, size):
    if self.nodes + nodes > _CAPS["data_nodes"] or self.size + size > _CAPS["canonical_plan_or_inventory_bytes"]:
      _fail()
    self.nodes += nodes
    self.size += size

  def append(self, destination, value):
    self.reserve(_native(value), len(_canonical(value, _CAPS["canonical_plan_or_inventory_bytes"])) + bool(destination))
    destination.append(value)


def _compile(declaration):
  digest = _digest(declaration, _CAPS["canonical_declaration_bytes"])
  inventory = {**copy.deepcopy(_FIXED), "declaration_digest": digest, "target": copy.deepcopy(declaration["target"]),
               "files": [], "directories": [], "requirements": [], "python_requirements": [], "stats": {}}
  plan = {**copy.deepcopy(_FIXED), "declaration_digest": digest, "plan_digest": "0" * 64,
          "target": copy.deepcopy(declaration["target"]), "roots": ["jsonschema", "pyyaml"], "extras": [],
          "archives": [], "files": [], "directories": [], "requirements": [], "python_requirements": [],
          "stats": {}, "inventory_template": inventory}
  budget = _Budget(plan)
  directory_map = {}
  def directory(path, source_id, explicit):
    target = _FIXED["library_root"] + "/" + path
    _path(target, _CAPS["target_path_bytes"])
    folded = target.casefold()
    if folded not in directory_map:
      if len(directory_map) + 2 >= _CAPS["planned_directories"]:
        _fail()
      skeleton = {"target": target, "mode": 448, "kind": "wheel-parent", "origins": []}
      # 最终两份目录记录提前保留；固定两根意味着这里均有逗号。
      budget.reserve(2 * _native(skeleton), 2 * (len(_canonical(skeleton, _CAPS["canonical_plan_or_inventory_bytes"])) + 1))
      directory_map[folded] = {**skeleton, "origins": {}}
    item = directory_map[folded]
    if item["target"] != target:
      _fail()
    key = (source_id, path)
    if key not in item["origins"]:
      origin = {"source_id": source_id, "member": path, "explicit": explicit}
      budget.reserve(2 * _native(origin), 2 * (len(_canonical(origin, _CAPS["canonical_plan_or_inventory_bytes"])) + bool(item["origins"])))
      item["origins"][key] = origin
    elif explicit and not item["origins"][key]["explicit"]:
      # false -> true 的 canonical 文本每份缩短一字节。
      budget.reserve(0, -2)
      item["origins"][key]["explicit"] = True
  files = []
  for row in declaration["wheels"]:
    source_id = row["source_id"]
    for member in row["members"]:
      target = _FIXED["library_root"] + "/" + member["path"]
      _path(target, _CAPS["target_path_bytes"])
      file = {"source_id": source_id, "member": member["path"], "target": target,
              "size": member["size"], "sha256": member["sha256"], "mode": 384, "role": member["role"]}
      # 临时文件列表本身也有界；预算在添加前覆盖两份最终记录。
      budget.append(plan["files"], file)
      budget.append(inventory["files"], copy.deepcopy(file))
      files.append(target)
      for parent in _parents(member["path"]):
        directory(parent, source_id, False)
    for path in row["explicit_directories"]:
      directory(path, source_id, True)
      for parent in _parents(path):
        directory(parent, source_id, False)
    budget.append(plan["archives"], {"source_id": source_id, "name": row["name"], "version": row["version"],
                                    "archive_size": row["archive_size"], "archive_sha256": row["archive_sha256"],
                                    "entry_count": len(row["members"]) + len(row["explicit_directories"]),
                                    "expanded_bytes": sum(member["size"] for member in row["members"])})
  file_set = _file_set(files + [_FIXED["inventory_path"]])
  for folded in directory_map:
    if folded in file_set or any(parent in file_set for parent in _parents(folded)):
      _fail()
  for fixed, kind in ((_PARENT, "bundle-root"), (_FIXED["library_root"], "library-root")):
    item = {"target": fixed, "mode": 448, "kind": kind, "origins": []}
    budget.append(plan["directories"], item)
    budget.append(inventory["directories"], copy.deepcopy(item))
  for item in sorted(directory_map.values(), key=lambda entry: entry["target"]):
    item["origins"] = [item["origins"][key] for key in sorted(item["origins"])]
    # 目录及每个 origin 已在构造前计入预算。
    plan["directories"].append(item)
    inventory["directories"].append(copy.deepcopy(item))
  requirements, python = _rules(declaration)
  for field, records in (("requirements", requirements), ("python_requirements", python)):
    for record in records:
      budget.append(plan[field], record)
      budget.append(inventory[field], copy.deepcopy(record))
  for container in (plan, inventory):
    container["files"].sort(key=lambda item: item["target"])
    container["directories"].sort(key=lambda item: item["target"])
  stats = {"raw_bytes": sum(row["archive_size"] for row in declaration["wheels"]),
           "file_bytes": sum(file["size"] for file in plan["files"]),
           "archive_entries": sum(archive["entry_count"] for archive in plan["archives"]),
           "file_count": len(plan["files"]), "directory_count": len(plan["directories"])}
  # stats 的大小固定且小；仍在赋值前用同一预算计入。
  for container in (plan, inventory):
    addition = {"stats": stats}
    budget.nodes += _native(addition) - 3
    budget.size += len(_canonical(stats, 1024)) - 2
    if budget.nodes > _CAPS["data_nodes"] or budget.size > _CAPS["canonical_plan_or_inventory_bytes"]:
      _fail()
    container["stats"] = copy.deepcopy(stats)
  _native(plan)
  _canonical(inventory, _CAPS["canonical_plan_or_inventory_bytes"])
  del plan["plan_digest"]
  plan["plan_digest"] = _digest(plan, _CAPS["canonical_plan_or_inventory_bytes"])
  _canonical(plan, _CAPS["canonical_plan_or_inventory_bytes"])
  return plan


def _occupied(occupied, plan):
  _native(occupied)
  _list(occupied, _CAPS["occupied_files"])
  paths = []
  for item in occupied:
    _shape(item, {"kind", "path"})
    if item["kind"] != "file":
      _fail()
    _path(item["path"], _CAPS["target_path_bytes"])
    paths.append(item["path"])
  if paths != sorted(set(paths)):
    _fail()
  old = _file_set(paths)
  reserved = _PARENT.casefold()
  for path in old:
    if path == reserved or path.startswith(reserved + "/") or path in set(_parents(reserved)):
      _fail()
  proposed = [item["target"] for item in plan["files"]] + [_FIXED["inventory_path"]]
  _file_set(paths + proposed)
  for item in plan["directories"]:
    path = item["target"].casefold()
    if path in old or any(parent in old for parent in _parents(path)):
      _fail()


def _attributes(internal, external, is_directory):
  if internal not in (0, 1):
    _fail()
  low, high = external & 0xffff, external >> 16
  mode_type = high & 0o170000
  if (high & ~(0o170000 | 0o777) or mode_type not in (0, 0o040000 if is_directory else 0o100000)
      or low not in ((0, 0x10) if is_directory else (0,))):
    _fail()


def _framing(raw, row):
  if len(raw) < 22:
    _fail()
  end = struct.unpack_from("<4s4H2IH", raw, len(raw) - 22)
  sig, disk, cd_disk, disk_count, count, cd_size, cd_offset, comment = end
  if (sig != b"PK\x05\x06" or disk or cd_disk or disk_count != count or comment
      or count == 65535 or cd_size == 0xffffffff or cd_offset == 0xffffffff
      or count > _CAPS["wheel_entries"] or count != len(row["members"]) + len(row["explicit_directories"])
      or cd_offset + cd_size != len(raw) - 22):
    _fail()
  members = {item["path"]: item for item in row["members"]}
  dirs = set(row["explicit_directories"])
  seen, records = set(), []
  cursor, expanded = cd_offset, 0
  ranges = []
  for unused in range(count):
    if cursor + 46 > len(raw) - 22:
      _fail()
    values = struct.unpack_from("<4s6H3I5H2I", raw, cursor)
    (signature, made, extract, flags, method, time, date, crc, compressed, size,
     name_len, extra_len, comment_len, start_disk, internal, external, offset) = values
    if (signature != b"PK\x01\x02" or made != (3 << 8 | 20) or extract != 20 or flags
        or method not in (0, 8) or extra_len or comment_len or start_disk
        or compressed == 0xffffffff or size == 0xffffffff or offset == 0xffffffff
        or not 1 <= name_len <= _CAPS["archive_member_path_bytes"] + 1
        or cursor + 46 + name_len > len(raw) - 22):
      _fail()
    name_bytes = raw[cursor + 46:cursor + 46 + name_len]
    name = name_bytes.decode("ascii", "strict")
    is_directory = name.endswith("/")
    path = name[:-1] if is_directory else name
    _member_path(row, path, is_directory)
    folded = path.casefold()
    if folded in seen:
      _fail()
    seen.add(folded)
    _attributes(internal, external, is_directory)
    _integer(size, 0, _CAPS["member_expanded_bytes"])
    if (size > _CAPS["compression_ratio"] * max(compressed, 1)
        or (method == 0 and compressed != size)):
      _fail()
    if is_directory:
      if path not in dirs or size or crc:
        _fail()
    elif path not in members or members[path]["size"] != size:
      _fail()
    if offset + 30 > cd_offset:
      _fail()
    local = struct.unpack_from("<4s5H3I2H", raw, offset)
    if local != (b"PK\x03\x04", extract, flags, method, time, date, crc, compressed, size, name_len, 0):
      _fail()
    start = offset + 30 + name_len
    if start + compressed > cd_offset or raw[offset + 30:start] != name_bytes:
      _fail()
    ranges.append((offset, start + compressed))
    expanded += size
    if expanded > _CAPS["wheel_expanded_bytes"]:
      _fail()
    records.append((path, is_directory, method, start, compressed, size, crc))
    cursor += 46 + name_len
  local_cursor = 0
  for offset, end_offset in sorted(ranges):
    if offset != local_cursor:
      _fail()
    local_cursor = end_offset
  if cursor != cd_offset + cd_size or local_cursor != cd_offset or seen != {path.casefold() for path in (*members, *dirs)}:
    _fail()
  return records


def _decode(raw, record, member, capture):
  path, directory, method, start, compressed, size, expected_crc = record
  digest, crc, total = hashlib.sha256(), 0, 0
  chunks = []
  def consume(chunk):
    nonlocal crc, total
    total += len(chunk)
    if total > size or total > _CAPS["member_expanded_bytes"]:
      _fail()
    digest.update(chunk)
    crc = zlib.crc32(chunk, crc)
    if capture:
      if total > _CAPS["metadata_member_bytes"]:
        _fail()
      chunks.append(chunk)
  if method == 0:
    for cursor in range(start, start + compressed, 65536):
      consume(raw[cursor:min(cursor + 65536, start + compressed)])
  else:
    decoder = zlib.decompressobj(-zlib.MAX_WBITS)
    for cursor in range(start, start + compressed, 65536):
      pending = raw[cursor:min(cursor + 65536, start + compressed)]
      while pending:
        previous = len(pending)
        output = decoder.decompress(pending, min(65536, size - total + 1))
        consume(output)
        pending = decoder.unconsumed_tail
        if decoder.unused_data or (not output and len(pending) == previous):
          _fail()
      if decoder.eof and cursor + 65536 < start + compressed:
        _fail()
    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
      _fail()
  if total != size or crc != expected_crc or (not directory and digest.hexdigest() != member["sha256"]):
    _fail()
  return b"".join(chunks) if capture else None


_FORBIDDEN_HEADERS = {name.lower() for name in ("Requires-External", "Requires", "Provides", "Obsoletes", "Provides-Dist", "Obsoletes-Dist", "Import-Name", "Import-Namespace")}
_DYNAMIC_FIELDS = {name.lower() for name in (
  "Author", "Author-email", "Classifier", "Description", "Description-Content-Type", "Download-URL", "Home-page", "Keywords",
  "License", "License-Expression", "License-File", "Maintainer", "Maintainer-email", "Obsoletes-Dist", "Platform", "Project-URL",
  "Provides-Dist", "Provides-Extra", "Requires-Dist", "Requires-External", "Requires-Python", "Summary", "Supported-Platform")}
_META_HEADER_MAP = {"metadata-version": "metadata_version", "name": "name", "version": "version", "requires-python": "requires_python",
                    "requires-dist": "requires_dist", "provides-extra": "provides_extra", "license-expression": "license_expression", "license": "legacy_license", "license-file": "license_files"}
_WHEEL_HEADER_MAP = {"wheel-version": "wheel_version", "root-is-purelib": "root_is_purelib", "tag": "tags", "build": "build"}


def _headers(payload, wanted, mapping, repeated, required):
  text = payload.decode("utf-8", "strict")
  # 逐行有界；正文不解释但已经完整 UTF8/哈希验证。
  values = {name: [] for name in mapping}
  last = None
  lines = 0
  for line in io.StringIO(text, newline=None):
    line = line.rstrip("\n")
    lines += 1
    if lines > _CAPS["header_lines"] or len(line.encode("utf-8")) > _CAPS["header_line_bytes"]:
      _fail()
    if not line:
      break
    if line.startswith((" ", "\t")):
      if last in mapping or last in (None, "dynamic"):
        _fail()
      continue
    match = re.fullmatch(r"([A-Za-z0-9-]+):[ \t]*(.*)", line)
    if not match:
      _fail()
    name, value = match[1].lower(), match[2]
    if name in _FORBIDDEN_HEADERS or any(ord(char) < 32 or ord(char) == 127 for char in value):
      _fail()
    # wheel 的 Dynamic 仅是信息标记；原实际字段仍完整匹配，不产生补全行为。
    if name == "dynamic" and (mapping is not _META_HEADER_MAP or not value.isascii() or value.lower() not in _DYNAMIC_FIELDS):
      _fail()
    last = name
    if name in mapping:
      values[name].append(value)
  for name, field in mapping.items():
    observed = values[name]
    if field in repeated:
      actual = observed
    else:
      if len(observed) > 1 or (field in required and len(observed) != 1):
        _fail()
      actual = observed[0] if observed else None
    if actual != wanted[field]:
      _fail()


def _record(payload, row):
  text = payload.decode("utf-8", "strict")
  members = {member["path"]: member for member in row["members"]}
  own = row["dist_info"] + "/RECORD"
  seen = set()
  for fields in csv.reader(io.StringIO(text, newline=""), strict=True):
    if len(fields) != 3 or len(seen) >= len(members):
      _fail()
    path, digest, size = fields
    _member_path(row, path)
    if path in seen or path not in members:
      _fail()
    seen.add(path)
    if path == own:
      if digest or size:
        _fail()
    else:
      member = members[path]
      expected = "sha256=" + base64.urlsafe_b64encode(bytes.fromhex(member["sha256"])).decode("ascii").rstrip("=")
      if digest != expected or size != str(member["size"]):
        _fail()
  if seen != set(members):
    _fail()


def _archive(raw, row):
  records = _framing(raw, row)
  members = {member["path"]: member for member in row["members"]}
  captured = {}
  metadata_total = 0
  for record in records:
    path, directory = record[:2]
    member = members.get(path)
    capture = not directory and member["role"] == "metadata"
    if capture:
      metadata_total += member["size"]
      if metadata_total > _CAPS["metadata_wheel_total_bytes"]:
        _fail()
    payload = _decode(raw, record, member, capture)
    if capture:
      captured[path] = payload
  dist = row["dist_info"]
  _headers(captured[dist + "/METADATA"], row["metadata"], _META_HEADER_MAP,
           {"requires_dist", "provides_extra", "license_files"}, {"metadata_version", "name", "version", "requires_python"})
  _headers(captured[dist + "/WHEEL"], row["wheel"], _WHEEL_HEADER_MAP, {"tags"}, {"wheel_version", "root_is_purelib"})
  if row["entry_points"] is not None and captured[row["entry_points"]["member"]] != _ENTRY_TEXT.encode("utf-8"):
    _fail()
  _record(captured[dist + "/RECORD"], row)


def _plan(declaration, artifacts, occupied):
  _declaration(declaration)
  plan = _compile(declaration)
  _occupied(occupied, plan)
  if (type(artifacts) is not dict or len(artifacts) != 7
      or any(type(key) is not str for key in artifacts)
      or set(artifacts) != {row["source_id"] for row in declaration["wheels"]}):
    _fail()
  raw_total = 0
  # 先核整个集合再解码任何档案。
  for row in declaration["wheels"]:
    raw = artifacts[row["source_id"]]
    if type(raw) is not bytes or not 1 <= len(raw) <= _CAPS["archive_bytes"]:
      _fail()
    raw_total += len(raw)
    if (raw_total > _CAPS["archive_set_bytes"] or len(raw) != row["archive_size"]
        or hashlib.sha256(raw).hexdigest() != row["archive_sha256"]):
      _fail()
  for row in declaration["wheels"]:
    _archive(artifacts[row["source_id"]], row)
  return plan


def _inventory(declaration, inventory):
  _declaration(declaration)
  _native(inventory)
  _canonical(inventory, _CAPS["canonical_plan_or_inventory_bytes"])
  expected = _compile(declaration)["inventory_template"]
  # canonical 比较同时区别 bool/int；字段/顺序必须逐项精确相同。
  if _canonical(inventory, _CAPS["canonical_plan_or_inventory_bytes"]) != _canonical(expected, _CAPS["canonical_plan_or_inventory_bytes"]):
    _fail()
