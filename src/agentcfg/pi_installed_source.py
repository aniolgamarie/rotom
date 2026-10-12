"""已安装Full的只读实际观察；结果不提供来源、角色或初始化资格。"""

import hashlib
import os
from pathlib import Path
import re
import stat

from .deployment import json_bytes
from .paths import relative_path
from .pi_lock_metadata import _Capture
from .storage import Tree


MAX_ENTRIES = 65536
MAX_FILE = 256 * 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024 * 1024
MAX_RECEIPT = 16 * 1024 * 1024
MAX_LINK = 4096
MAX_RESULT = 32 * 1024 * 1024
_MARKERS = {".agentcfg-ready": "ready", ".agentcfg-receipt.json": "receipt"}
_REQUIRED = frozenset({"engine", "source_ids", "package_path", "lock_path", "package_json_digest", "package_lock_digest", "entrypoint",
  "resource_manifest", "resource_manifest_digest", "capability_ids", "identity"})
_ALLOWED = _REQUIRED | {"runtime_files", "ai_package", "python_bundle", "durable_owner"}


def _decimal(value, bits, *, signed=False):
  if type(value) is not str or not 1 <= len(value) <= (20 if bits == 64 else 10): raise ValueError()
  expression = r"(?:0|-?[1-9][0-9]*)" if signed else r"(?:0|[1-9][0-9]*)"
  if re.fullmatch(expression, value) is None: raise ValueError()
  number = int(value)
  lower, upper = (-(1 << (bits - 1)), 1 << (bits - 1)) if signed else (0, 1 << bits)
  if not lower <= number < upper: raise ValueError()
  return value


def _physical(info, *, directory=False):
  fields = {"device": (info.st_dev, 64, False), "inode": (info.st_ino, 64, False), "uid": (info.st_uid, 32, False), "mode": (info.st_mode, 32, False)}
  if not directory:
    fields.update(size=(info.st_size, 64, False), mtime_ns=(info.st_mtime_ns, 64, True), ctime_ns=(info.st_ctime_ns, 64, True), nlink=(info.st_nlink, 64, False))
  result = {}
  for name, (value, bits, signed) in fields.items():
    if type(value) is not int: raise ValueError()
    result[name] = _decimal(str(value), bits, signed=signed)
  return result


def _directory(info):
  if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o6022: raise ValueError()
  return _physical(info, directory=True)


def _read_file(tree, path, *, cap, remaining, collect=False):
  with tree.parent(path) as (parent, name):
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or before.st_nlink != 1 or before.st_mode & 0o6022: raise ValueError()
    physical = _physical(before)
    with tree.open_read(path, max_bytes=cap) as (stream, opened):
      if _physical(opened) != physical or opened.st_size > remaining: raise ValueError()
      checksum = hashlib.sha256(); count = 0; chunks = [] if collect else None
      while True:
        chunk = stream.read(65536)
        if not chunk: break
        count += len(chunk)
        if count > opened.st_size or count > cap or count > remaining: raise ValueError()
        checksum.update(chunk)
        if collect: chunks.append(chunk)
      if count != opened.st_size or _physical(os.fstat(stream.fileno())) != physical: raise ValueError()
    after = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if _physical(after) != physical: raise ValueError()
  return physical, checksum.hexdigest(), b"".join(chunks) if collect else None, count


def _marker(tree, path, identity):
  cap = 65 if path == ".agentcfg-ready" else MAX_RECEIPT
  physical, sha, raw, _ = _read_file(tree, path, cap=cap, remaining=cap, collect=True)
  if int(physical["mode"]) != stat.S_IFREG | 0o600: raise ValueError()
  if path == ".agentcfg-ready" and raw != (identity + "\n").encode(): raise ValueError()
  return {"physical": physical, "sha256": sha}, raw


def _link(tree, parent, name, path, before):
  if before.st_uid != os.geteuid() or before.st_nlink != 1 or not stat.S_ISLNK(before.st_mode): raise ValueError()
  physical = _physical(before)
  target = os.readlink(name, dir_fd=parent)
  if type(target) is not str or len(target) > MAX_LINK or len(target.encode("utf-8", "strict")) > MAX_LINK: raise ValueError()
  if not (tree.root / path).resolve(strict=True).is_relative_to(tree.root): raise ValueError()
  after = os.stat(name, dir_fd=parent, follow_symlinks=False)
  if _physical(after) != physical: raise ValueError()
  return {"kind": "link", "physical": physical, "target": target}


def _scan(tree, expected, *, stat_only=False):
  entries = {}; pending = [""]; total = 0; seen = set()
  while pending:
    directory = pending.pop()
    locator = (directory + "/" if directory else "") + ".agentcfg-observation-locator"
    # basename仅定位既有父目录，不创建/读取它。
    with tree.parent(locator) as (parent, _):
      directory_info = os.fstat(parent)
      projection = _directory(directory_info)
      if directory and projection != entries[directory]["physical"]: raise ValueError()
      with os.scandir(parent) as children:
        for entry in children:
          path = (directory + "/" if directory else "") + entry.name
          if path in seen: raise ValueError()
          seen.add(path)
          if path in _MARKERS: continue
          if len(entries) >= MAX_ENTRIES: raise ValueError()
          if relative_path(path).as_posix() != path: raise ValueError()
          path.encode("utf-8", "strict")
          if path not in expected: raise ValueError()
          before = os.stat(entry.name, dir_fd=parent, follow_symlinks=False)
          locked = expected[path]
          if stat.S_ISDIR(before.st_mode):
            if set(locked) != {"kind"} or locked["kind"] != "directory": raise ValueError()
            row = {"kind": "directory", "physical": _directory(before)}
            pending.append(path)
          elif stat.S_ISLNK(before.st_mode):
            if set(locked) != {"kind", "target"} or locked["kind"] != "link": raise ValueError()
            row = _link(tree, parent, entry.name, path, before)
            if row["target"] != locked["target"]: raise ValueError()
          elif stat.S_ISREG(before.st_mode):
            if set(locked) != {"kind", "sha256", "mode"} or locked["kind"] != "file": raise ValueError()
            if before.st_uid != os.geteuid() or before.st_nlink != 1 or before.st_mode & 0o6022: raise ValueError()
            if before.st_size > MAX_FILE or before.st_size > MAX_TOTAL - total: raise ValueError()
            if stat.S_IMODE(before.st_mode) != locked["mode"]: raise ValueError()
            if stat_only:
              physical, sha, count = _physical(before), locked["sha256"], before.st_size
            else:
              physical, sha, _, count = _read_file(tree, path, cap=MAX_FILE, remaining=MAX_TOTAL - total)
              if physical != _physical(before) or sha != locked["sha256"]: raise ValueError()
            total += count
            row = {"kind": "file", "physical": physical, "sha256": sha}
          else:
            raise ValueError()
          entries[path] = row
  if set(entries) != set(expected): raise ValueError()
  return {name: entries[name] for name in sorted(entries)}


def _finish(tree, root_physical, entries, markers, expected, identity):
  if _scan(tree, expected, stat_only=True) != entries: raise ValueError()
  for path, slot in _MARKERS.items():
    marker, _ = _marker(tree, path, identity)
    if marker != markers[slot]: raise ValueError()
  if _directory(os.fstat(tree.fd)) != root_physical: raise ValueError()
  with Tree(tree.root) as named:
    if named.fd is None or _directory(os.fstat(named.fd)) != root_physical: raise ValueError()


def _inputs(root, piece, identity, lock_identity, platform, toolchains, binding_identity):
  if type(root) is not str or not 1 <= len(root) <= 4096: raise ValueError()
  if len(root.encode("utf-8", "strict")) > 4096 or "\x00" in root or not root.startswith("/") or root == "/" or ".." in root.split("/"): raise ValueError()
  owned_path = Path(root)
  if owned_path.parts == (owned_path.anchor,): raise ValueError()
  capture = _Capture()
  piece = capture.capture(piece)
  tools = _Capture().capture(toolchains)
  binding = _Capture().capture(binding_identity)
  if (type(piece) is not dict or not _REQUIRED <= set(piece) <= _ALLOWED or "durable_owner" not in piece
      or type(piece["engine"]) is not str or piece["engine"] != "node" or type(binding) is not dict or binding.get("profile") != "pi-full"): raise ValueError()
  from .pi_owner_origin import _context
  from .pi_modern_launcher import _owner_rows
  path, context = _context(root, identity, lock_identity, platform, tools, binding)
  _owner_rows(piece["durable_owner"], piece["runtime_files"], piece["python_bundle"], locked=True)
  if hashlib.sha256(json_bytes({key: value for key, value in piece.items() if key != "identity"})).hexdigest() != piece["identity"]: raise ValueError()
  base = hashlib.sha256(json_bytes({"lock_identity": context["lock_identity"], "slice_identity": piece["identity"], "platform": context["platform"],
    "toolchain_identity": hashlib.sha256(json_bytes(context["toolchains"])).hexdigest()})).hexdigest()
  if context["binding_identity"]["slice"] != hashlib.sha256(json_bytes(piece)).hexdigest() or context["binding_identity"]["runtime"] != base: raise ValueError()
  return path, piece, context


def _capture(root, piece, *, identity, lock_identity, platform, toolchains, binding_identity):
  root, piece, context = _inputs(root, piece, identity, lock_identity, platform, toolchains, binding_identity)
  with Tree(root) as tree:
    if tree.fd is None: raise ValueError()
    root_physical = _directory(os.fstat(tree.fd))
    markers = {}; raw_markers = {}
    for path, slot in _MARKERS.items(): markers[slot], raw_markers[slot] = _marker(tree, path, context["identity"])
    from .pi_runtime_packages import _validated_receipt, owned
    if not owned(root, context["identity"]): raise ValueError()
    shared = _validated_receipt(root, context["identity"])
    if shared is None: raise ValueError()
    receipt, shared_raw = shared
    if (raw_markers["receipt"] != shared_raw or type(receipt["schema_version"]) is not int or receipt["schema_version"] != 2
        or receipt["slice"] != piece or receipt["identity"] != context["identity"] or receipt["lock_identity"] != context["lock_identity"]
        or receipt["platform"] != context["platform"] or receipt["toolchains"] != context["toolchains"] or receipt["binding_identity"] != context["binding_identity"]): raise ValueError()
    from .pi_owner_origin import validate_installed_owner_origin
    validate_installed_owner_origin(root, piece, **context)
    entries = _scan(tree, receipt["files"])
    _finish(tree, root_physical, entries, markers, receipt["files"], context["identity"])
    result = {"schema_version": 1, "profile": "pi-full", "lock_identity": context["lock_identity"], "runtime_identity": context["identity"],
      "root": root_physical, "markers": markers, "entries": entries}
    if len(json_bytes(result)) > MAX_RESULT: raise ValueError()
    return result


def _boundary(function, *args, **kwargs):
  failed = False
  try: result = function(*args, **kwargs)
  except Exception: failed = True
  if failed:
    try: raise ValueError("pi-installed-source")
    except ValueError as error:
      error.__cause__ = None; error.__context__ = None
      raise
  return result


def capture_installed_full_source(root, piece, *, identity, lock_identity, platform, toolchains, binding_identity):
  """返回私有detached数据；没有Full/source/initializer资格或连续FDhold外观。"""
  return _boundary(_capture, root, piece, identity=identity, lock_identity=lock_identity, platform=platform,
    toolchains=toolchains, binding_identity=binding_identity)
