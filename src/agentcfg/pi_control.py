"""私有 Unix 控制通道；每次调用使用独立客户端进程，业务 cwd 不受影响。"""

import ctypes
import json
import os
from pathlib import Path
import socket
import stat
import struct
import sys

from .deployment import json_bytes
from .storage import Conflict, Tree


MAX_FRAME = 1024 * 1024


def read_frame(stream):
  data = stream.readline(MAX_FRAME + 1)
  if not data or len(data) > MAX_FRAME or not data.endswith(b"\n"):
    raise Conflict("监督消息缺失或超过长度限制")
  try:
    value = json.loads(data)
  except (ValueError, UnicodeError):
    raise Conflict("监督消息格式无效") from None
  if not isinstance(value, dict):
    raise Conflict("监督消息必须是对象")
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
      raise Conflict("无法验证Unix控制通道用户身份")
    return uid.value
  raise Conflict("此平台没有实现Unix控制身份校验")


def request(endpoint, capability, message):
  endpoint = Path(endpoint)
  with Tree(endpoint.parent) as tree:
    raw = tree.read(endpoint.name)
    if raw is None or raw[1] != 0o600:
      raise Conflict("监督端点记录缺失或不安全")
    try:
      record = json.loads(raw[0])
      if set(record) != {"schema_version", "owner", "socket_name", "socket_identity", "user_capability"} or record["schema_version"] != 1 or record["socket_name"] != "control.sock":
        raise ValueError()
      info = os.stat(record["socket_name"], dir_fd=tree.fd, follow_symlinks=False)
      expected = record["socket_identity"]
      if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid() or (info.st_dev, info.st_ino) != (expected["device"], expected["inode"]):
        raise ValueError()
    except (ValueError, KeyError, TypeError, OSError):
      raise Conflict("监督端点身份已改变") from None
    body = json_bytes({"capability": capability, "message": message})
    if len(body) > MAX_FRAME:
      raise Conflict("监督请求超过长度限制")
    # AF_UNIX 的 pathname 长度有限；仅客户端子进程暂时进入已验证目录。
    cwd = os.open(".", os.O_RDONLY | os.O_DIRECTORY)
    try:
      os.fchdir(tree.fd)
      connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
      connection.settimeout(30)
      try:
        connection.connect(record["socket_name"])
      finally:
        os.fchdir(cwd)
      if peer_uid(connection) != os.geteuid():
        raise Conflict("监督端点用户不匹配")
      with connection, connection.makefile("rwb") as stream:
        stream.write(body)
        stream.flush()
        return read_frame(stream)
    finally:
      os.fchdir(cwd)
      os.close(cwd)
