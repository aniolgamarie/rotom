"""私有 Unix 控制通道；每次调用使用独立客户端进程，业务 cwd 不受影响。"""

import ctypes
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import stat
import struct
import sys

from .deployment import json_bytes
from .storage import Conflict, Tree, identity


MAX_FRAME = 1024 * 1024
DIRECTORY_ENV = "AGENTCFG_SUPERVISOR_DIRECTORY_IDENTITY"


@contextmanager
def control_directory(endpoint, expected):
  """仅控制记录可用父监督者验证过的精确目录；不改变通用路径规则。"""
  if expected is None:
    with Tree(endpoint.parent) as tree:
      yield tree.fd, tree.read(endpoint.name, max_bytes=MAX_FRAME)
    return
  if (not endpoint.is_absolute() or endpoint.name != "control.json" or ".." in endpoint.parts
      or not isinstance(expected, dict) or set(expected) != {"device", "inode", "uid"}
      or any(type(expected[key]) is not int or expected[key] < 0 for key in expected)):
    raise Conflict("监督目录身份声明无效")
  fd = None
  try:
    fd = os.open(endpoint.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    directory = os.fstat(fd)
    if (stat.S_IMODE(directory.st_mode) != 0o700 or directory.st_uid != os.geteuid()
        or expected != {"device": directory.st_dev, "inode": directory.st_ino, "uid": directory.st_uid}):
      raise Conflict("监督目录身份已改变")
    # 固定文件名、只读、单链接及完整前后身份；不能用于任意目标或受管写入。
    before = os.stat("control.json", dir_fd=fd, follow_symlinks=False)
    def checked(info):
      return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= MAX_FRAME)
    if not checked(before):
      raise Conflict("监督端点记录不安全")
    source = os.open("control.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
    with os.fdopen(source, "rb") as stream:
      opened = os.fstat(stream.fileno())
      if identity(opened) != identity(before) or not checked(opened):
        raise Conflict("监督端点在读取前发生变化")
      content = stream.read(MAX_FRAME + 1)
      after = os.fstat(stream.fileno())
      if len(content) > MAX_FRAME or not checked(after) or identity(opened) != identity(after):
        raise Conflict("监督端点在读取时发生变化")
    current = os.stat("control.json", dir_fd=fd, follow_symlinks=False)
    if not checked(current) or identity(opened) != identity(current):
      raise Conflict("监督端点路径在读取时发生变化")
    yield fd, (content, 0o600, identity(opened))
  except OSError:
    raise Conflict("无法安全读取监督端点") from None
  finally:
    if fd is not None:
      os.close(fd)


def runtime_request(endpoint, capability, message):
  """密封运行包入口显式采用父进程接线；普通 request 不读取环境。"""
  value = os.environ.get(DIRECTORY_ENV)
  if value is None:
    return request(endpoint, capability, message)
  try:
    expected = json.loads(value)
    if not isinstance(expected, dict):
      raise ValueError()
  except (ValueError, TypeError):
    raise Conflict("监督目录身份声明无效") from None
  return request(endpoint, capability, message, directory_identity=expected)


def endpoint_for_owner(state_root, owner):
  """只定位指定控制者；旧端点仅在完整归属一致时兼容，不扫描其他运行。"""
  from .activity import OWNER_KEYS
  from .paths import PathError, read_private_file, safe_id
  from .pi_catalog import validate
  from .schema import ConfigError
  try:
    if not isinstance(owner, dict) or set(owner) != set(OWNER_KEYS):
      raise ValueError()
    activation = safe_id(owner["supervisor_activation_id"])
    validate("process-identity", owner["supervisor_process_identity"])
    root = Path(state_root)
    with Tree(root):
      endpoint = root / "activity/control" / activation / "control.json"
      try:
        content = read_private_file(endpoint)
      except FileNotFoundError:
        endpoint = root / "activity/control/control.json"
        content = read_private_file(endpoint)
    record = json.loads(content)
    if (set(record) != {"schema_version", "owner", "socket_name", "socket_identity", "user_capability"}
        or record["schema_version"] != 1 or record["owner"] != owner
        or record["socket_name"] != "control.sock" or not isinstance(record["user_capability"], str)
        or not record["user_capability"]):
      raise ValueError()
    return endpoint, record
  except (OSError, PathError, ConfigError, ValueError, TypeError, KeyError):
    raise Conflict("监督端点缺失、不安全或控制者不匹配") from None


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


def request(endpoint, capability, message, *, directory_identity=None):
  endpoint = Path(endpoint)
  with control_directory(endpoint, directory_identity) as (directory_fd, raw):
    if raw is None or raw[1] != 0o600:
      raise Conflict("监督端点记录缺失或不安全")
    try:
      record = json.loads(raw[0])
      if set(record) != {"schema_version", "owner", "socket_name", "socket_identity", "user_capability"} or record["schema_version"] != 1 or record["socket_name"] != "control.sock":
        raise ValueError()
      info = os.stat(record["socket_name"], dir_fd=directory_fd, follow_symlinks=False)
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
      os.fchdir(directory_fd)
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
