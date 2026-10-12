"""显式账户授权CLI：只读私有文档或显式create/update，不启用reviewer。"""
import json
import os
from pathlib import Path
import re
import stat

from .paths import _absolute_directory
from .pi_reviewer_authority import ReviewerAuthorityStore
from .pi_reviewer_authority_protocol import decode_authority
from .schema import ConfigError

MAX_BYTES = 16384


def _invalid():
  raise ConfigError("PI_RISK_REVIEW_AUTHORITY_INVALID") from None


def _snapshot(info):
  return (info.st_dev, info.st_ino, info.st_uid, info.st_mode, info.st_nlink,
    info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _parent_identity(info):
  return (info.st_dev, info.st_ino, info.st_uid, info.st_mode)


def read_document(value):
  """不展开HOME、不穿透链接；同FD读取后复核叶名和父目录物理身份。"""
  try:
    text = os.fspath(value)
    if type(text) is not str or not text or any(ord(char) < 32 or ord(char) == 127 for char in text): _invalid()
    path = Path(os.path.abspath(text))
    with _absolute_directory(path.parent) as parent:
      parent_identity = _parent_identity(os.fstat(parent))
      before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
      if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or before.st_nlink != 1
          or stat.S_IMODE(before.st_mode) != 0o600 or not 1 <= before.st_size <= MAX_BYTES): _invalid()
      source = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
      try:
        if _snapshot(os.fstat(source)) != _snapshot(before): _invalid()
        data = bytearray()
        while len(data) <= MAX_BYTES:
          try: chunk = os.read(source, MAX_BYTES + 1 - len(data))
          except InterruptedError: continue
          if not chunk: break
          data.extend(chunk)
        if len(data) != before.st_size or len(data) > MAX_BYTES: _invalid()
        if _snapshot(os.fstat(source)) != _snapshot(before): _invalid()
        if _snapshot(os.stat(path.name, dir_fd=parent, follow_symlinks=False)) != _snapshot(before): _invalid()
        if _parent_identity(os.fstat(parent)) != parent_identity: _invalid()
        with _absolute_directory(path.parent) as current:
          if _parent_identity(os.fstat(current)) != parent_identity: _invalid()
      finally: os.close(source)
    return decode_authority(bytes(data))
  except Exception:
    _invalid()


def cmd_reviewer_authority(args):
  action = args.authority_command
  document = None
  if action == "update":
    if type(args.expected_identity) is not str or not re.fullmatch("[0-9a-f]{64}", args.expected_identity): _invalid()
  if action in ("create", "update"): document = read_document(args.document)
  # 私有源/expected已通过才允许passwd根查询；不会构造预算账本、秘密或SDK。
  store = ReviewerAuthorityStore()
  if action == "show": snapshot = store.read(); status = "observed"
  elif action == "create": snapshot = store.create(document); status = "created"
  elif action == "update": snapshot = store.update(document, expected_identity=args.expected_identity); status = "updated"
  else: _invalid()
  output = {"schema_version": 1, "status": status, "authority": snapshot, "product_gate": False}
  if args.format == "json": print(json.dumps(output, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
  else:
    value = snapshot["document"]; route = value["route"]; limits = value["limits"]
    whole, fractional = divmod(limits["max_cost_units"], 10**9)
    print(f"授权工件 {status}：generation={value['generation']}")
    print(f"路线：{route['logical_provider']} / {route['native_route']} / {route['model_id']}")
    print(f"累计上限：调用次数={limits['max_calls']}，估算费用={whole}.{fractional:09d} {limits['currency']}")
    print(f"当前标识：{snapshot['identity']}")
    print(f"有效时段：[{value['valid_from']}, {value['valid_until']})")
    print("仅授权工件，未启用自动审批或产品运行。")
  return 0
