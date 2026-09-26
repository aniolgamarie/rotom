"""OMP固定来源下载：有限重试、严格续传与内容寻址缓存。"""

from contextlib import contextmanager
import fcntl
import hashlib
import http.client
import os
from pathlib import Path
import re
import socket
import stat
import time
import urllib.error
import urllib.request

from .process import DependencyError
from .storage import Tree, ensure_private


MAX_ASSET_BYTES = 512 * 1024 * 1024
MAX_LOCK_BYTES = 128 * 1024 * 1024
ATTEMPTS = 3
CHUNK = 1024 * 1024
_DIGEST = re.compile(r"[a-f0-9]{64}")
_CONTENT_RANGE = re.compile(r"bytes ([0-9]+)-([0-9]+)/([0-9]+|\*)")


class _TransferFailure(Exception):
  def __init__(self, category, *, retryable):
    self.category = category
    self.retryable = retryable


def _validate_url(url):
  from .config import _credential_url
  if not isinstance(url, str) or not url.startswith("https://") or _credential_url(url):
    raise DependencyError("OMP依赖来源URL无效")


def _request(url, *, offset=0):
  headers = {"User-Agent": "agentcfg"}
  if offset:
    headers["Range"] = f"bytes={offset}-"
  return urllib.request.Request(url, headers=headers)


def _category(error):
  if isinstance(error, urllib.error.HTTPError):
    retryable = error.code in (408, 429) or 500 <= error.code <= 599
    return _TransferFailure(f"http-{error.code}", retryable=retryable)
  reason = error.reason if isinstance(error, urllib.error.URLError) else error
  if isinstance(reason, http.client.IncompleteRead):
    return _TransferFailure("short-read", retryable=True)
  if isinstance(reason, (TimeoutError, socket.timeout)):
    return _TransferFailure("timeout", retryable=True)
  if isinstance(reason, (ConnectionError, OSError)):
    return _TransferFailure("connection", retryable=True)
  return _TransferFailure("transport", retryable=False)


def _fail(category, attempt, progress):
  raise DependencyError(f"OMP下载失败 category={category} attempt={attempt} progress={progress}") from None


def _status(response):
  value = getattr(response, "status", None)
  if value is None and hasattr(response, "getcode"):
    value = response.getcode()
  return value or 200


def _length(headers):
  raw = headers.get("Content-Length")
  if raw is None:
    return None
  try:
    value = int(raw)
  except (TypeError, ValueError):
    raise _TransferFailure("response-shape", retryable=False) from None
  if value < 0:
    raise _TransferFailure("response-shape", retryable=False)
  return value


def _response_shape(response, offset, maximum):
  status = _status(response)
  headers = response.headers
  length = _length(headers)
  total = None
  if status == 206:
    match = _CONTENT_RANGE.fullmatch(headers.get("Content-Range", ""))
    if match is None or int(match.group(1)) != offset:
      raise _TransferFailure("content-range", retryable=False)
    start, end = int(match.group(1)), int(match.group(2))
    total = None if match.group(3) == "*" else int(match.group(3))
    if end < start or length is not None and length != end - start + 1:
      raise _TransferFailure("content-range", retryable=False)
    length = end - start + 1
    if total is not None and (end >= total or total > maximum):
      raise _TransferFailure("size-limit", retryable=False)
  elif status == 200:
    offset = 0
    total = length
  else:
    raise _TransferFailure(f"http-{status}", retryable=status in (408, 429) or 500 <= status <= 599)
  if length is not None and offset + length > maximum:
    raise _TransferFailure("size-limit", retryable=False)
  return offset, length, total


def _read_response(response, output, *, offset, maximum):
  write_offset, length, total = _response_shape(response, offset, maximum)
  if write_offset == 0:
    os.ftruncate(output, 0)
  os.lseek(output, write_offset, os.SEEK_SET)
  received = 0
  try:
    while True:
      chunk = response.read(CHUNK)
      if not chunk:
        break
      if not isinstance(chunk, bytes) or write_offset + received + len(chunk) > maximum:
        raise _TransferFailure("size-limit", retryable=False)
      view = memoryview(chunk)
      while view:
        try:
          written = os.write(output, view)
        except OSError:
          raise _TransferFailure("cache-write", retryable=False) from None
        if written <= 0:
          raise _TransferFailure("cache-write", retryable=False)
        view = view[written:]
      received += len(chunk)
  finally:
    try:
      os.fsync(output)
    except OSError:
      raise _TransferFailure("cache-write", retryable=False) from None
  size = write_offset + received
  if length is not None and received != length or total is not None and size != total:
    raise _TransferFailure("short-read", retryable=True)
  return size, total


def _hash_fd(fd, maximum):
  info = os.fstat(fd)
  if info.st_size > maximum:
    raise _TransferFailure("size-limit", retryable=False)
  digest = hashlib.sha256()
  os.lseek(fd, 0, os.SEEK_SET)
  while chunk := os.read(fd, CHUNK):
    digest.update(chunk)
  return digest.hexdigest(), info.st_size


@contextmanager
def _download_lock(tree, digest):
  name = "." + digest + ".lock"
  with tree.parent(name) as (parent, target):
    fd = os.open(target, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
  try:
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
        or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
      raise DependencyError("OMP下载缓存锁无效")
    fcntl.flock(fd, fcntl.LOCK_EX)
    yield
  finally:
    os.close(fd)


def _open_part(tree, name):
  with tree.parent(name) as (parent, target):
    fd = os.open(target, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
  info = os.fstat(fd)
  if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
      or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
    os.close(fd)
    raise DependencyError("OMP下载partial缓存无效")
  return fd


def _valid_final(tree, name, digest, maximum):
  try:
    with tree.open_read(name) as (stream, info):
      if info.st_mode & 0o777 != 0o600:
        raise DependencyError("OMP下载缓存权限无效")
      if info.st_size > maximum:
        return False
      checksum = hashlib.sha256()
      while chunk := stream.read(CHUNK):
        checksum.update(chunk)
    return checksum.hexdigest() == digest
  except FileNotFoundError:
    return None


def ensure_cached_asset(cache_root, url, expected_sha256, *, maximum=None):
  """确保完整发行物位于内容寻址缓存；网络失败保留可验证partial。"""
  _validate_url(url)
  if not isinstance(expected_sha256, str) or _DIGEST.fullmatch(expected_sha256) is None:
    raise DependencyError("OMP下载摘要无效")
  maximum = MAX_ASSET_BYTES if maximum is None else maximum
  ensure_private(Path(cache_root))
  with Tree(Path(cache_root)) as tree, _download_lock(tree, expected_sha256):
    final = Path(cache_root) / expected_sha256
    valid = _valid_final(tree, expected_sha256, expected_sha256, maximum)
    if valid is not None:
      if valid:
        return final
      with tree.parent(expected_sha256) as (parent, name):
        os.unlink(name, dir_fd=parent)
        os.fsync(parent)
    part_name = expected_sha256 + ".part"
    fd = _open_part(tree, part_name)
    try:
      partial_digest, progress = _hash_fd(fd, maximum)
      if partial_digest == expected_sha256:
        with tree.parent(part_name) as (parent, source):
          os.replace(source, expected_sha256, src_dir_fd=parent, dst_dir_fd=parent)
          os.fsync(parent)
        return final
      for attempt in range(1, ATTEMPTS + 1):
        try:
          request = _request(url, offset=progress)
          with urllib.request.urlopen(request, timeout=60) as response:
            progress, total = _read_response(response, fd, offset=progress, maximum=maximum)
          actual, progress = _hash_fd(fd, maximum)
          if actual == expected_sha256:
            with tree.parent(part_name) as (parent, source):
              os.replace(source, expected_sha256, src_dir_fd=parent, dst_dir_fd=parent)
              os.fsync(parent)
            return final
          if total is not None and progress == total:
            # 已有partial可能损坏；只通过重新从零下载修复，不发布错误摘要。
            os.ftruncate(fd, 0)
            os.fsync(fd)
            progress = 0
            failure = _TransferFailure("integrity", retryable=attempt < ATTEMPTS)
          else:
            failure = _TransferFailure("short-read", retryable=True)
        except _TransferFailure as error:
          failure = error
          progress = os.fstat(fd).st_size
        except Exception as error:
          if isinstance(error, urllib.error.HTTPError) and error.code == 416 and progress:
            os.ftruncate(fd, 0)
            os.fsync(fd)
            progress = 0
            failure = _TransferFailure("range-reset", retryable=True)
          else:
            failure = _category(error)
          progress = os.fstat(fd).st_size
        if not failure.retryable or attempt == ATTEMPTS:
          _fail(failure.category, attempt, progress)
        time.sleep(0.25 * 2 ** (attempt - 1))
    finally:
      os.close(fd)


def download_bytes(url, *, maximum=MAX_LOCK_BYTES):
  """锁维护输入使用有限重试；不写运行资产cache。"""
  _validate_url(url)
  for attempt in range(1, ATTEMPTS + 1):
    progress = 0
    try:
      request = _request(url)
      result = bytearray()
      with urllib.request.urlopen(request, timeout=60) as response:
        _, length, _ = _response_shape(response, 0, maximum)
        while True:
          chunk = response.read(CHUNK)
          if not chunk:
            break
          if len(result) + len(chunk) > maximum:
            raise _TransferFailure("size-limit", retryable=False)
          result.extend(chunk)
          progress = len(result)
        if length is not None and progress != length:
          raise _TransferFailure("short-read", retryable=True)
      return bytes(result)
    except _TransferFailure as error:
      failure = error
    except Exception as error:
      failure = _category(error)
    if not failure.retryable or attempt == ATTEMPTS:
      _fail(failure.category, attempt, progress)
    time.sleep(0.25 * 2 ** (attempt - 1))
