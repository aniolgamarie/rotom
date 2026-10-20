"""原子发布仅操作临时目录；不启动宿主或读取真实会话。"""
import importlib.util
import os
from pathlib import Path
import stat

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
  spec = importlib.util.spec_from_file_location(name, path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


bench = load("atomic_bench", ROOT / "tools/bench/herdr_upgrade.py")
producer = load("atomic_producer", ROOT / "tests/fixtures/herdr-bench/v1/producer.py")


@pytest.fixture
def publication_root(tmp_path):
  directory = tmp_path / "publication"
  directory.mkdir(mode=0o700)
  return directory


def test_runner_final_is_single_link_at_directory_fsync(publication_root, monkeypatch):
  path = publication_root / "barrier.json"
  fsync = os.fsync
  seen = []
  def inspect(fd):
    if stat.S_ISDIR(os.fstat(fd).st_mode):
      seen.append(producer.load_private(path))
      assert path.stat().st_nlink == 1
    fsync(fd)
  monkeypatch.setattr(os, "fsync", inspect)
  bench.write_new(path, {"phase": "measure"}, private=True)
  assert seen == [{"phase": "measure"}]


def test_producer_final_not_visible_before_file_fsync(publication_root, monkeypatch):
  path = publication_root / "ready.json"
  fsync = os.fsync
  seen = []
  def inspect(fd):
    if stat.S_ISREG(os.fstat(fd).st_mode):
      seen.append(True)
      assert not path.exists()
    fsync(fd)
  monkeypatch.setattr(os, "fsync", inspect)
  producer.write_new(path, {"phase": "measure"})
  assert seen and producer.load_private(path) == {"phase": "measure"}


@pytest.fixture(params=[bench, producer], ids=["runner", "producer"])
def writer(request):
  return request.param


def descriptors():
  return set(os.listdir("/proc/self/fd"))


def test_publish_is_complete_single_link_at_rename(writer, publication_root, monkeypatch):
  path = publication_root / "receipt.json"
  original = writer._rename_noreplace
  seen = []
  payload = {"value": "x" * 1000}
  def inspect(directory, temporary, destination):
    assert not path.exists()
    assert producer.load_private(path.parent / temporary) == payload
    assert not os.get_inheritable(directory)
    seen.append(True)
    original(directory, temporary, destination)
  monkeypatch.setattr(writer, "_rename_noreplace", inspect)
  before = descriptors()
  writer.write_new(path, payload)
  assert seen == [True] and producer.load_private(path) == payload
  assert descriptors() == before and list(publication_root.iterdir()) == [path]


@pytest.mark.parametrize("symlink", [False, True])
def test_existing_name_never_overwritten(writer, publication_root, symlink):
  path = publication_root / "receipt.json"
  if symlink:
    path.symlink_to("absent-target")
  else:
    writer.write_new(path, {"old": True})
  before = path.lstat()
  with pytest.raises(bench.BenchError if writer is bench else FileExistsError) as error:
    writer.write_new(path, {"new": True})
  if writer is bench:
    assert error.value.code == 4 and error.value.reason == "output_exists"
  assert path.lstat() == before
  if symlink:
    assert path.is_symlink()
  else:
    assert producer.load_private(path) == {"old": True}
  assert list(publication_root.iterdir()) == [path]


@pytest.mark.parametrize("missing", ["symbol", "libc", "ENOSYS", "EINVAL", "EOPNOTSUPP"])
def test_unavailable_fails_closed_without_fallback(writer, publication_root, monkeypatch, missing):
  import errno
  path = publication_root / "receipt.json"
  def forbidden(*args, **kwargs):
    pytest.fail("publication fallback")
  for name in ("link", "rename", "replace"):
    monkeypatch.setattr(os, name, forbidden)
  if missing == "symbol":
    monkeypatch.setattr(writer.ctypes, "CDLL", lambda *args, **kwargs: object())
  elif missing == "libc":
    def no_libc(*args, **kwargs):
      raise OSError(errno.ENOENT, "synthetic")
    monkeypatch.setattr(writer.ctypes, "CDLL", no_libc)
  else:
    class Unsupported:
      def __call__(self, *args):
        writer.ctypes.set_errno(getattr(errno, missing))
        return -1
    class Libc:
      renameat2 = Unsupported()
    monkeypatch.setattr(writer.ctypes, "CDLL", lambda *args, **kwargs: Libc())
  before = descriptors()
  with pytest.raises(bench.BenchError if writer is bench else ValueError) as error:
    writer.write_new(path, {"new": True})
  if writer is bench:
    assert (error.value.code, error.value.reason) == (5, "atomic_publish_unavailable")
  else:
    assert error.value.args == ("atomic_publish_unavailable",)
  assert not list(publication_root.iterdir()) and descriptors() == before


@pytest.mark.parametrize("at_directory", [False, True])
def test_fsync_error_closes_descriptors_and_retains_published_name(writer, publication_root, monkeypatch, at_directory):
  import errno
  path = publication_root / "receipt.json"
  fsync = os.fsync
  def fail(fd):
    if stat.S_ISDIR(os.fstat(fd).st_mode) == at_directory:
      raise OSError(errno.EIO, "synthetic")
    fsync(fd)
  monkeypatch.setattr(os, "fsync", fail)
  before = descriptors()
  with pytest.raises(OSError) as error:
    writer.write_new(path, {"new": True})
  assert error.value.errno == errno.EIO and descriptors() == before
  assert list(publication_root.iterdir()) == ([path] if at_directory else [])
  if at_directory:
    assert producer.load_private(path) == {"new": True}


def test_simultaneous_publish_has_one_winner(writer, publication_root, monkeypatch):
  from concurrent.futures import ThreadPoolExecutor
  from threading import Barrier
  path = publication_root / "receipt.json"
  rendezvous = Barrier(2)
  original = writer._rename_noreplace
  def publish(*args):
    rendezvous.wait(timeout=5)
    original(*args)
  monkeypatch.setattr(writer, "_rename_noreplace", publish)
  def attempt(value):
    try:
      writer.write_new(path, {"winner": value})
      return value
    except (bench.BenchError, FileExistsError) as error:
      if writer is bench:
        assert error.code == 4 and error.reason == "output_exists"
      return None
  before = descriptors()
  with ThreadPoolExecutor(max_workers=2) as pool:
    outcomes = list(pool.map(attempt, [1, 2]))
  winners = [x for x in outcomes if x is not None]
  assert len(winners) == 1 and producer.load_private(path) == {"winner": winners[0]}
  assert descriptors() == before and list(publication_root.iterdir()) == [path]


@pytest.mark.parametrize("reason,token", [
  ("Herdr API rejected request", "herdr_api_rejected_request"),
  ("Herdr endpoint changed", "herdr_endpoint_changed"),
  ("Herdr mutation result is unknown", "herdr_mutation_result_unknown"),
  ("Herdr operation deadline expired", "herdr_operation_deadline_expired"),
  ("Herdr API rejected request synthetic_secret", None),
  ("synthetic_secret_valid_format", None),
])
def test_termcfg_failure_only_maps_exact_fixed_literals(publication_root, reason, token):
  from termcfg.errors import TermcfgError
  _, name, _ = bench._record_native_failure(publication_root, "output-30", "output", 1,
    "case-runtime", TermcfgError(4, reason), 4).split(":")
  raw = producer.load_private(publication_root / name)
  assert raw["exception_category"] == "termcfg" and raw["reason_code"] == token
  assert raw["exit_code"] == 4
  assert b"synthetic_secret" not in (publication_root / name).read_bytes()


def test_stage_disappearing_does_not_mask_original_io_error(writer, publication_root, monkeypatch):
  import errno
  path = publication_root / "receipt.json"
  original_error = OSError(errno.EIO, "synthetic")
  def fail(directory, temporary, destination):
    os.unlink(temporary, dir_fd=directory)
    raise original_error
  monkeypatch.setattr(writer, "_rename_noreplace", fail)
  before = descriptors()
  with pytest.raises(OSError) as error:
    writer.write_new(path, {"new": True})
  assert error.value is original_error
  assert descriptors() == before and not list(publication_root.iterdir())


def test_non_linux_never_attempts_publish(writer, publication_root, monkeypatch):
  monkeypatch.setattr(writer.sys, "platform", "unsupported")
  monkeypatch.setattr(writer.ctypes, "CDLL", lambda *args, **kwargs: pytest.fail("non-Linux libc"))
  before = descriptors()
  with pytest.raises(bench.BenchError if writer is bench else ValueError) as error:
    writer.write_new(publication_root / "receipt.json", {})
  if writer is bench:
    assert (error.value.code, error.value.reason) == (5, "atomic_publish_unavailable")
  else:
    assert error.value.args == ("atomic_publish_unavailable",)
  assert descriptors() == before and not list(publication_root.iterdir())
