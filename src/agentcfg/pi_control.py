"""私有 Unix 控制通道；每次调用使用独立客户端进程，业务 cwd 不受影响。"""

import ctypes
import json
import math
import os
from pathlib import Path
import socket
import stat
import struct
import sys
from contextlib import contextmanager

from .storage import Conflict, Tree


MAX_FRAME = 1024 * 1024


class _HeldControlDirectory:
  """仅control.json的held-FD只读入口；不重新打开路径祖先，不提供写方法。"""
  def __init__(self, borrowed):
    if type(borrowed) is not int or borrowed < 3:
      _fixed_error(Conflict, "监督目录描述符无效")
    self.fd = None
    try:
      info = os.fstat(borrowed)
      if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError()
      os.set_inheritable(borrowed, False)
      self.fd = os.dup(borrowed)
      self.expected = self._identity(info)
      self._check()
    except (OSError, ValueError, Conflict):
      self.close()
      _fixed_error(Conflict, "监督目录描述符无效")

  @staticmethod
  def _identity(info): return (info.st_dev, info.st_ino, info.st_uid, info.st_mode)

  def _check(self):
    if self.fd is None or self._identity(os.fstat(self.fd)) != self.expected:
      _fixed_error(Conflict, "监督目录描述符已改变")

  @contextmanager
  def parent(self, path, *, create=False):
    if path != "control.json" or create:
      _fixed_error(Conflict, "监督目录只允许读取固定端点")
    self._check()
    yield self.fd, "control.json"
    self._check()

  # 原Tree的普通单链接/no-follow/有界/前后文件身份检查原样复用。
  open_read = Tree.open_read
  read = Tree.read

  def close(self):
    if self.fd is not None:
      owned, self.fd = self.fd, None
      os.close(owned)

  def __enter__(self): return self
  def __exit__(self, *args): self.close()


def _fixed_error(kind, message):
  error = kind(message)
  try:
    raise error
  except (Conflict, ValueError):
    # 清除实际链，仅修改本函数新建的固定异常。
    error.__context__ = None
    error.__cause__ = None
    raise


def _json_pairs(items):
  value = {}
  for key, child in items:
    if key in value: _fixed_error(ValueError, "监督消息格式无效")
    value[key] = child
  return value


def _json_constant(_value): _fixed_error(ValueError, "监督消息格式无效")


def _json_float(value):
  result = float(value)
  if not math.isfinite(result): _fixed_error(ValueError, "监督消息格式无效")
  return result


def _decode_json(data):
  if type(data) is not bytes or len(data) > MAX_FRAME: _fixed_error(ValueError, "监督消息格式无效")
  failed = False
  try:
    value = json.loads(bytes.decode(data, "utf-8", "strict"), object_pairs_hook=_json_pairs,
      parse_constant=_json_constant, parse_float=_json_float)
  except (ValueError, UnicodeError, RecursionError): failed = True
  if failed: _fixed_error(ValueError, "监督消息格式无效")
  return value


def read_frame(stream):
  data = stream.readline(MAX_FRAME + 1)
  if type(data) is not bytes: _fixed_error(Conflict, "监督消息格式无效")
  if not data or len(data) > MAX_FRAME or not data.endswith(b"\n"):
    _fixed_error(Conflict, "监督消息缺失或超过长度限制")
  failed = False
  try: value = _decode_json(data)
  except ValueError: failed = True
  if failed: _fixed_error(Conflict, "监督消息格式无效")
  if not isinstance(value, dict): _fixed_error(Conflict, "监督消息必须是对象")
  return value


def peer_uid(connection):
  if sys.platform == "linux":
    return struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))[1]
  if sys.platform == "darwin":
    library = ctypes.CDLL(None, use_errno=True)
    uid, gid = ctypes.c_uint(), ctypes.c_uint()
    call = library.getpeereid
    call.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
    call.restype = ctypes.c_int
    if call(connection.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
      _fixed_error(Conflict, "无法验证Unix控制通道用户身份")
    return uid.value
  _fixed_error(Conflict, "此平台没有实现Unix控制身份校验")


def request(endpoint, capability, message, *, inherited_directory_fd=None):
  endpoint = Path(endpoint)
  if inherited_directory_fd is not None and endpoint.name != "control.json":
    _fixed_error(Conflict, "监督目录只允许读取固定端点")
  with (Tree(endpoint.parent) if inherited_directory_fd is None else _HeldControlDirectory(inherited_directory_fd)) as tree:
    read_failed = False
    try: raw = tree.read(endpoint.name, max_bytes=MAX_FRAME)
    except Conflict: read_failed = True
    if read_failed: _fixed_error(Conflict, "监督端点身份已改变")
    if raw is None or raw[1] != 0o600:
      _fixed_error(Conflict, "监督端点记录缺失或不安全")
    failed = False
    try:
      record = _decode_json(raw[0])
      if set(record) != {"schema_version", "owner", "socket_name", "socket_identity", "user_capability"} or record["schema_version"] != 1 or record["socket_name"] != "control.sock":
        raise ValueError()
      info = os.stat(record["socket_name"], dir_fd=tree.fd, follow_symlinks=False)
      expected = record["socket_identity"]
      if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid() or (info.st_dev, info.st_ino) != (expected["device"], expected["inode"]):
        raise ValueError()
    except (ValueError, KeyError, TypeError, OSError): failed = True
    if failed: _fixed_error(Conflict, "监督端点身份已改变")
    # 短命客户端只需固定wire字节，不为序列化加载配置/部署模块。
    body = (json.dumps({"capability": capability, "message": message}, ensure_ascii=False,
      sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n").encode()
    if len(body) > MAX_FRAME:
      _fixed_error(Conflict, "监督请求超过长度限制")
    # AF_UNIX 的 pathname 长度有限；仅客户端子进程暂时进入已验证目录。
    cwd = os.open(".", os.O_RDONLY | os.O_DIRECTORY)
    connection = None
    guarded = False
    try:
      os.fchdir(tree.fd)
      connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
      connection.settimeout(30)
      try:
        connection.connect(record["socket_name"])
      finally:
        os.fchdir(cwd)
      if peer_uid(connection) != os.geteuid():
        _fixed_error(Conflict, "监督端点用户不匹配")
      guarded = True
      with connection, connection.makefile("rwb") as stream:
        stream.write(body)
        stream.flush()
        return read_frame(stream)
    finally:
      if connection is not None and not guarded: connection.close()
      os.fchdir(cwd)
      os.close(cwd)
