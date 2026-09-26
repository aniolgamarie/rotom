import hashlib
from pathlib import Path
import urllib.error

import pytest

from agentcfg.omp_download import MAX_ASSET_BYTES, download_bytes, ensure_cached_asset
from agentcfg.process import DependencyError


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
  monkeypatch.setattr("agentcfg.omp_download.time.sleep", lambda _: None)


def digest(value):
  return hashlib.sha256(value).hexdigest()


class Response:
  def __init__(self, chunks, *, status=200, headers=None, failure=None):
    self.chunks = list(chunks)
    self.status = status
    self.headers = headers or {}
    self.failure = failure

  def __enter__(self):
    return self

  def __exit__(self, *args):
    return False

  def read(self, size=-1):
    if self.chunks:
      return self.chunks.pop(0)
    if self.failure is not None:
      failure, self.failure = self.failure, None
      raise failure
    return b""


def test_asset_download_resumes_after_interrupted_read(tmp_path, monkeypatch):
  content = b"0123456789abcdef"
  calls = []

  def open_fake(request, timeout):
    calls.append((request, timeout))
    if len(calls) == 1:
      return Response([content[:6]], headers={"Content-Length": str(len(content))},
        failure=ConnectionResetError("private upstream detail"))
    assert request.get_header("Range") == "bytes=6-"
    return Response([content[6:]], status=206,
      headers={"Content-Range": f"bytes 6-{len(content) - 1}/{len(content)}",
        "Content-Length": str(len(content) - 6)})

  monkeypatch.setattr("agentcfg.omp_download.urllib.request.urlopen", open_fake)
  path = ensure_cached_asset(tmp_path / "downloads", "https://example.invalid/omp", digest(content))
  assert path.read_bytes() == content
  assert len(calls) == 2 and all(timeout == 60 for _, timeout in calls)
  assert not list(path.parent.glob("*.part"))


def test_range_ignored_with_200_restarts_from_zero(tmp_path, monkeypatch):
  content = b"complete-release"
  root = tmp_path / "downloads"
  root.mkdir(mode=0o700)
  part = root / (digest(content) + ".part")
  part.write_bytes(b"stale-prefix")
  part.chmod(0o600)
  seen = []

  def open_fake(request, timeout):
    seen.append(request.get_header("Range"))
    return Response([content], status=200, headers={"Content-Length": str(len(content))})

  monkeypatch.setattr("agentcfg.omp_download.urllib.request.urlopen", open_fake)
  assert ensure_cached_asset(root, "https://example.invalid/omp", digest(content)).read_bytes() == content
  assert seen == ["bytes=12-"]


def test_complete_partial_publishes_offline_and_bad_content_range_fails_closed(tmp_path, monkeypatch):
  content = b"complete-partial"
  root = tmp_path / "downloads"
  root.mkdir(mode=0o700)
  part = root / (digest(content) + ".part")
  part.write_bytes(content)
  part.chmod(0o600)
  monkeypatch.setattr("agentcfg.omp_download.urllib.request.urlopen",
    lambda *args, **kwargs: pytest.fail("complete partial must publish offline"))
  assert ensure_cached_asset(root, "https://example.invalid/omp", digest(content)).read_bytes() == content

  other = b"expected-other"
  calls = []
  def invalid_range(request, timeout):
    calls.append(request.get_header("Range"))
    return Response([other[3:]], status=206,
      headers={"Content-Range": f"bytes 0-{len(other) - 1}/{len(other)}"})
  monkeypatch.setattr("agentcfg.omp_download.urllib.request.urlopen", invalid_range)
  other_part = root / (digest(other) + ".part")
  other_part.write_bytes(other[:3])
  other_part.chmod(0o600)
  with pytest.raises(DependencyError, match="category=content-range"):
    ensure_cached_asset(root, "https://example.invalid/omp", digest(other))
  assert calls == ["bytes=3-"] and other_part.read_bytes() == other[:3]


def test_short_reads_keep_partial_and_exhaust_three_attempts(tmp_path, monkeypatch):
  content = b"abcdefghij"
  calls = []

  def open_fake(request, timeout):
    start = int((request.get_header("Range") or "bytes=0-").removeprefix("bytes=").removesuffix("-"))
    calls.append(start)
    end = min(start + 1, len(content) - 1)
    return Response([content[start:end + 1]], status=206 if start else 200,
      headers={"Content-Length": str(len(content) - start),
        **({"Content-Range": f"bytes {start}-{len(content) - 1}/{len(content)}"} if start else {})})

  monkeypatch.setattr("agentcfg.omp_download.urllib.request.urlopen", open_fake)
  with pytest.raises(DependencyError) as caught:
    ensure_cached_asset(tmp_path / "downloads", "https://example.invalid/private", digest(content))
  assert calls == [0, 2, 4]
  assert (tmp_path / "downloads" / (digest(content) + ".part")).read_bytes() == content[:6]
  assert "attempt=3" in str(caught.value) and "progress=6" in str(caught.value)
  assert "example.invalid" not in str(caught.value) and "private" not in str(caught.value)


def test_transient_http_retries_but_nontransient_does_not(tmp_path, monkeypatch):
  content = b"release"
  calls = []

  def transient(request, timeout):
    calls.append(None)
    if len(calls) < 3:
      raise urllib.error.HTTPError(request.full_url, 503, "unavailable", {}, None)
    return Response([content], headers={"Content-Length": str(len(content))})

  monkeypatch.setattr("agentcfg.omp_download.urllib.request.urlopen", transient)
  assert ensure_cached_asset(tmp_path / "downloads", "https://example.invalid/omp", digest(content)).read_bytes() == content
  assert len(calls) == 3

  calls.clear()
  def missing(request, timeout):
    calls.append(None)
    raise urllib.error.HTTPError(request.full_url, 404, "missing", {}, None)
  monkeypatch.setattr("agentcfg.omp_download.urllib.request.urlopen", missing)
  with pytest.raises(DependencyError, match="category=http-404"):
    ensure_cached_asset(tmp_path / "other", "https://example.invalid/omp", digest(b"other"))
  assert len(calls) == 1


def test_valid_cache_is_offline_and_corrupt_cache_redownloads_once(tmp_path, monkeypatch):
  content = b"trusted"
  root = tmp_path / "downloads"
  root.mkdir(mode=0o700)
  target = root / digest(content)
  target.write_bytes(content)
  target.chmod(0o600)
  monkeypatch.setattr("agentcfg.omp_download.urllib.request.urlopen",
    lambda *args, **kwargs: pytest.fail("valid cache must remain offline"))
  assert ensure_cached_asset(root, "https://example.invalid/omp", digest(content)) == target

  target.write_bytes(b"corrupt")
  calls = []
  def repair(request, timeout):
    calls.append(None)
    return Response([content], headers={"Content-Length": str(len(content))})
  monkeypatch.setattr("agentcfg.omp_download.urllib.request.urlopen", repair)
  assert ensure_cached_asset(root, "https://example.invalid/omp", digest(content)).read_bytes() == content
  assert len(calls) == 1


def test_asset_limit_and_lock_download_retry_are_bounded(tmp_path, monkeypatch):
  monkeypatch.setattr("agentcfg.omp_download.MAX_ASSET_BYTES", 4)
  monkeypatch.setattr("agentcfg.omp_download.urllib.request.urlopen",
    lambda request, timeout: Response([b"12345"], headers={"Content-Length": "5"}))
  with pytest.raises(DependencyError, match="category=size-limit"):
    ensure_cached_asset(tmp_path / "downloads", "https://example.invalid/omp", digest(b"12345"))

  calls = []
  def flaky(request, timeout):
    calls.append(None)
    if len(calls) < 3:
      raise TimeoutError()
    return Response([b"lock-input"], headers={"Content-Length": "10"})
  monkeypatch.setattr("agentcfg.omp_download.urllib.request.urlopen", flaky)
  assert download_bytes("https://example.invalid/lock") == b"lock-input"
  assert len(calls) == 3 and MAX_ASSET_BYTES >= 512 * 1024 * 1024


def test_chunked_incomplete_read_retries_and_bad_complete_partial_restarts(tmp_path, monkeypatch):
  import http.client
  content = b"expected-complete-release"
  calls = []

  def open_fake(request, timeout):
    calls.append(request.get_header("Range"))
    if len(calls) == 1:
      return Response([content[:4]], failure=http.client.IncompleteRead(b"lost", 10))
    return Response([content[4:]], status=206, headers={
      "Content-Range": f"bytes 4-{len(content) - 1}/{len(content)}", "Content-Length": str(len(content) - 4)})

  monkeypatch.setattr("agentcfg.omp_download.urllib.request.urlopen", open_fake)
  assert ensure_cached_asset(tmp_path / "chunked", "https://example.invalid/omp", digest(content)).read_bytes() == content
  assert calls == [None, "bytes=4-"]
  calls.clear()

  def bad_then_good(request, timeout):
    calls.append(request.get_header("Range"))
    return Response([b"x" * len(content) if len(calls) == 1 else content], headers={"Content-Length": str(len(content))})

  monkeypatch.setattr("agentcfg.omp_download.urllib.request.urlopen", bad_then_good)
  assert ensure_cached_asset(tmp_path / "wrong-full", "https://example.invalid/omp", digest(content)).read_bytes() == content
  assert calls == [None, None]


def test_range_body_must_match_declared_span_without_content_length(tmp_path, monkeypatch):
  content = b"abcdefghij"
  # SHA虽然正确，服务端声明的206分片跨度仍必须与正文一致。
  monkeypatch.setattr("agentcfg.omp_download.urllib.request.urlopen", lambda *a, **kw:
    Response([content], status=206, headers={"Content-Range": "bytes 0-3/10"}))
  with pytest.raises(DependencyError):
    ensure_cached_asset(tmp_path / "range-span", "https://example.invalid/omp", digest(content))
  assert not (tmp_path / "range-span" / digest(content)).exists()
