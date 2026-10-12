"""探针专用info协议；真实本进程pipe与局部IO替身，不启动namespace/helper。"""

from contextlib import contextmanager
import importlib
import json
import os
from types import SimpleNamespace

import pytest

from agentcfg.schema import ConfigError


BASE = {"child-pid": 201, "mnt-namespace": 301, "pid-namespace": 401}
OPTIONAL = ("user-namespace", "ipc-namespace", "net-namespace", "uts-namespace", "cgroup-namespace")


def module():
  return importlib.import_module("agentcfg.pi_shell_probe_info")


@contextmanager
def pipe(data):
  read, write = os.pipe()
  try:
    assert len(data) <= 4096
    os.write(write, data); os.close(write); write = None
    yield read
  finally:
    os.close(read)
    if write is not None: os.close(write)


def refused(fd, **kwargs):
  with pytest.raises(ConfigError) as caught: module().read_namespace_info(fd, **kwargs)
  assert caught.value.code == "pi-shell-probe-info"
  assert str(caught.value) == "配置校验失败: pi-shell-probe-info"


@pytest.mark.parametrize("extra", [(), OPTIONAL])
def test_real_pipe_accepts_fixed_bwrap_info_at_eof(extra):
  value = {**BASE, **{key: 501 + index for index, key in enumerate(extra)}}
  with pipe(json.dumps(value).encode()) as fd:
    assert module().read_namespace_info(fd) == value
    os.fstat(fd)  # 输入FD所有权不属于parser。


def mocked(monkeypatch, chunks, *, clock=None, selectable=True):
  value = module(); reads = []; waits = []; pending = iter(chunks)
  proxy = SimpleNamespace(**vars(os))
  def read(fd, size):
    assert fd == 17 and size > 0; reads.append(size)
    item = next(pending)
    if isinstance(item, BaseException): raise item
    return item
  proxy.read = read; monkeypatch.setattr(value, "os", proxy)
  class Poll:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def register(self, fd, event): assert fd == 17
    def select(self, timeout): waits.append(timeout); return [object()] if selectable else []
  monkeypatch.setattr(value, "selectors", SimpleNamespace(DefaultSelector=Poll, EVENT_READ=1))
  ticks = iter(clock if clock is not None else [0] * 1000)
  monkeypatch.setattr(value, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
  return reads, waits


def test_fragmented_json_is_collected_until_eof(monkeypatch):
  raw = json.dumps(BASE).encode(); reads, _ = mocked(monkeypatch, [raw[:2], raw[2:13], raw[13:], b""])
  assert module().read_namespace_info(17) == BASE and len(reads) == 4


def test_complete_json_is_not_returned_before_later_bytes_or_eof(monkeypatch):
  mocked(monkeypatch, [json.dumps(BASE).encode(), b"\n{\"secret\":1}", b""])
  refused(17)


def test_read_interruption_retries_within_deadline(monkeypatch):
  mocked(monkeypatch, [InterruptedError(), json.dumps(BASE).encode(), b""])
  assert module().read_namespace_info(17) == BASE


@pytest.mark.parametrize("raw", [b"", b"{", b"null", b"[]", b"{}", b"not-json-secret", b"\xff", b' {"child-pid":1} ',
  b'{"child-pid":1,"child-pid":2,"mnt-namespace":3,"pid-namespace":4}',
  b'{"child-pid":NaN,"mnt-namespace":3,"pid-namespace":4}',
  b'{"child-pid":Infinity,"mnt-namespace":3,"pid-namespace":4}'])
def test_malformed_and_duplicate_json_is_fixed_error(raw):
  with pipe(raw) as fd: refused(fd)


@pytest.mark.parametrize("field", [*BASE, *OPTIONAL])
@pytest.mark.parametrize("bad", [True, False, 0, -1, 2**63, 1.0, "secret", None])
def test_all_namespace_ids_are_exact_positive_bounded_integers(field, bad):
  value = {**BASE, field: bad}
  with pipe(json.dumps(value).encode()) as fd: refused(fd)


@pytest.mark.parametrize("missing", BASE)
def test_all_three_primary_fields_are_required(missing):
  value = dict(BASE); del value[missing]
  with pipe(json.dumps(value).encode()) as fd: refused(fd)


def test_unknown_field_rejects_instead_of_loosening_production_schema():
  with pipe(json.dumps({**BASE, "time-namespace": 50}).encode()) as fd: refused(fd)


def test_maximum_integer_is_allowed():
  value = {key: 2**63 - 1 for key in BASE}
  with pipe(json.dumps(value).encode()) as fd: assert module().read_namespace_info(fd) == value


@pytest.mark.parametrize("length", [65535, 65536])
def test_total_byte_limit_includes_trailing_whitespace(monkeypatch, length):
  raw = json.dumps(BASE).encode(); raw += b" " * (length - len(raw))
  chunks = [raw[i:i + 1024] for i in range(0, len(raw), 1024)] + [b""]
  mocked(monkeypatch, chunks)
  if length == 65535: assert module().read_namespace_info(17) == BASE
  else: refused(17)


def test_timeout_after_complete_json_without_eof_rejects(monkeypatch):
  reads, waits = mocked(monkeypatch, [json.dumps(BASE).encode()], clock=[0, 0, 0, 11])
  refused(17, timeout=10)
  assert len(reads) == 1 and len(waits) == 1


def test_selector_timeout_is_fixed_error(monkeypatch):
  reads, _ = mocked(monkeypatch, [], selectable=False)
  refused(17); assert reads == []


def test_real_pipe_without_writer_eof_times_out():
  read, write = os.pipe()
  try: refused(read, timeout=0.001)
  finally: os.close(read); os.close(write)


@pytest.mark.parametrize("timeout", [False, 0, -1, float("nan"), float("inf"), "secret"])
def test_invalid_timeout_is_fixed_error(timeout):
  with pipe(json.dumps(BASE).encode()) as fd: refused(fd, timeout=timeout)


def test_underlying_read_error_is_sanitized(monkeypatch):
  mocked(monkeypatch, [OSError("secret path")])
  refused(17)


def test_bad_fd_is_fixed_error():
  refused(-1)


def test_readiness_arriving_after_deadline_is_not_accepted(monkeypatch):
  reads, _ = mocked(monkeypatch, [json.dumps(BASE).encode(), b""], clock=[0, 0, 11])
  refused(17, timeout=10)
  assert reads == []


@pytest.mark.parametrize("fd", [True, None, "secret"])
def test_invalid_descriptor_types_are_fixed_error(fd):
  refused(fd)
