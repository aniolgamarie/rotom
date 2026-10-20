"""同UID互斥、容量和迟到metadata必须读回验证。"""

import os
from pathlib import Path
from types import SimpleNamespace
import threading
import time

import pytest

from termcfg.errors import TermcfgError
from termcfg.work import operation_lock, report_tokens


class Deadline:
  def remaining(self, limit=None):
    return min(limit or 1, 1)


def test_lock_has_private_stable_empty_inode(tmp_path):
  path = tmp_path / "lock-root"
  with operation_lock(Deadline(), root=path):
    lock = path / "operation.lock"
    before = lock.stat().st_ino
    assert lock.stat().st_mode & 0o777 == 0o600
    assert path.stat().st_mode & 0o777 == 0o700
    assert lock.read_bytes() == b""
  with operation_lock(Deadline(), root=path):
    assert lock.stat().st_ino == before


def test_lock_never_adopts_unsafe_directory_or_link(tmp_path):
  path = tmp_path / "unsafe"
  path.mkdir(mode=0o755)
  path.chmod(0o755)
  with pytest.raises(TermcfgError) as error:
    with operation_lock(Deadline(), root=path):
      pytest.fail("unsafe lock admitted")
  assert error.value.code == 4
  path.chmod(0o700)
  (path / "operation.lock").symlink_to(tmp_path / "not-a-lock")
  with pytest.raises(TermcfgError):
    with operation_lock(Deadline(), root=path):
      pytest.fail("symlink lock admitted")


def test_same_user_lock_serializes_independent_callers(tmp_path):
  active = 0
  maximum = 0
  path = tmp_path / "mutex"
  barrier = threading.Barrier(10)
  errors = []
  def caller():
    nonlocal active, maximum
    try:
      barrier.wait()
      with operation_lock(Deadline(), root=path):
        active += 1
        maximum = max(maximum, active)
        time.sleep(0.002)
        active -= 1
    except BaseException as error:
      errors.append(error)
  threads = [threading.Thread(target=caller) for _ in range(10)]
  for thread in threads: thread.start()
  for thread in threads: thread.join()
  assert not errors and maximum == 1


class MetadataClient:
  def __init__(self, tokens=None, ignore=False):
    self.tokens = dict(tokens or {})
    self.ignore = ignore
    self.requests = []
  def request(self, method, params):
    self.requests.append((method, params))
    if method.endswith("report_metadata"):
      if not self.ignore:
        for key, value in params["tokens"].items():
          if value is None: self.tokens.pop(key, None)
          else: self.tokens[key] = value
      return {"type": "ok"}
    return {"tokens": dict(self.tokens)}


def test_patch_must_read_back_and_preserve_other_sources():
  client = MetadataClient({"foreign": "keep"})
  report_tokens(client, "workspace", "w1", {"rw_epoch": "a" * 32})
  assert client.tokens == {"foreign": "keep", "rw_epoch": "a" * 32}
  with pytest.raises(TermcfgError) as error:
    report_tokens(MetadataClient(ignore=True), "workspace", "w1", {"rw_epoch": "a" * 32})
  assert error.value.code == 4


@pytest.mark.parametrize("patch", [{"bad.key": "a"}, {"a": "x" * 81}, {"a": "中文"},
  {str(i): "x" for i in range(17)}])
def test_invalid_metadata_is_not_silently_normalized(patch):
  client = MetadataClient()
  with pytest.raises(TermcfgError):
    report_tokens(client, "workspace", "w1", patch)
  assert not client.requests


def test_capacity_conflict_never_deletes_other_keys():
  client = MetadataClient({"foreign%d" % i: "keep" for i in range(32)})
  with pytest.raises(TermcfgError) as error:
    report_tokens(client, "workspace", "w1", {"rw_epoch": "a" * 32})
  assert error.value.code == 4
  assert len(client.tokens) == 32
  assert all(not m.endswith("report_metadata") for m, _ in client.requests)
