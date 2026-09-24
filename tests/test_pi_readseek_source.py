"""源码构建默认只用Git、编译器和二进制替身，不下载或执行ReadSeek。"""
from pathlib import Path
import json
import shutil
import pytest
from agentcfg.pi_readseek_source import build_source, read_recipe
from agentcfg.process import DependencyError
from agentcfg.storage import ensure_private

ROOT = Path(__file__).resolve().parents[1]


def test_source_recipe_covers_fixed_native_closure():
  recipe = read_recipe(ROOT)
  assert len(recipe["pdfium_dependencies"]["git"]) >= 10
  assert recipe["source"]["commit"] == "ce9aec937bdd2666b77bb95c2fcd5898b95fd625"
  assert recipe["zig_version"] == "0.16.0"
  assert set(recipe["submodules"]) == {"sqlite", "zig-clap", "zigimg"}


@pytest.mark.parametrize("fault", ["commit", "artifact", "zig"])
def test_unpinned_recipe_is_rejected(tmp_path, fault):
  recipe = read_recipe(ROOT)
  if fault == "commit": recipe["submodules"]["sqlite"]["commit"] = "main"
  if fault == "artifact": recipe["pdfium_dependencies"]["artifacts"]["darwin-x64"][0]["sha256"] = "unverified"
  if fault == "zig": recipe["zig_version"] = "latest"
  path = tmp_path / "agents/pi/build"; path.mkdir(parents=True)
  (path / "readseek-source.json").write_text(json.dumps(recipe))
  with pytest.raises(DependencyError): read_recipe(tmp_path)


def test_wrong_host_never_runs_or_resolves_build_commands(tmp_path):
  with pytest.raises(DependencyError):
    build_source(ROOT, tmp_path, host=("linux", "x86_64"), run=lambda *a, **k: pytest.fail("must not execute"), which=lambda _: pytest.fail("must not inspect"))


@pytest.mark.parametrize("fault", [None, "wrong-version", "wrong-source", "wrong-submodule", "wrong-arch", "license"])
def test_source_build_verifies_inputs_output_and_preserves_not_run(tmp_path, monkeypatch, fault):
  import agentcfg.pi_readseek_source as source
  recipe = read_recipe(ROOT)
  # 测试源码不是实际下载；输入摘要以本测试提供的内容重算。
  import hashlib
  contents = {name: b"synthetic source" for name in recipe["input_digests"]}
  contents["packages/readseek/scripts/pdfium-deps.lock"] = json.dumps(recipe["pdfium_dependencies"]).encode()
  recipe["input_digests"] = {name: hashlib.sha256(raw).hexdigest() for name, raw in contents.items()}
  monkeypatch.setattr(source, "read_recipe", lambda _: recipe)
  calls, commits = [], {}
  def run(argv, *, cwd, env):
    calls.append(argv)
    assert env["HOME"] != str(Path.home()) and "SSH_AUTH_SOCK" not in env and "OPENAI_API_KEY" not in env
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    if argv[-1] == "version": return "0.17.0" if fault == "wrong-version" else "0.16.0"
    if argv[-1] == "--show-sdk-version": return "15.4"
    if "fetch" in argv:
      target = Path(argv[argv.index("-C") + 1]); commits[str(target)] = argv[-1]
      if target.name == "source":
        for name, raw in contents.items():
          path = target / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw if fault != "wrong-source" else b"changed")
      return ""
    if "rev-parse" in argv: return commits[argv[argv.index("-C") + 1]]
    if "--stage" in argv:
      name = Path(argv[-1]).name; return "160000 " + ("f" * 40 if fault == "wrong-submodule" else recipe["submodules"][name]["commit"]) + " 0\t" + argv[-1]
    if "build" in argv and argv[0].endswith("zig"):
      path = Path(argv[argv.index("--prefix") + 1]) / "bin/readseek"; path.parent.mkdir(parents=True)
      raw = bytearray(64); raw[:4] = b"\xcf\xfa\xed\xfe"; raw[4:8] = (0x100000c if fault == "wrong-arch" else 0x1000007).to_bytes(4,"little"); raw[12:16] = (2).to_bytes(4,"little")
      path.write_bytes(raw); path.chmod(0o700)
      return ""
    if "ls-files" in argv:
      target = Path(argv[argv.index("-C") + 1]); target.mkdir(parents=True, exist_ok=True)
      (target / "LICENSE").write_text("synthetic license")
      return "" if fault == "license" else "LICENSE\0"
    return ""
  ensure_private(tmp_path)
  call = lambda: build_source(ROOT, tmp_path, host=("darwin", "x86_64"), run=run, which=lambda name: "/fixture/" + name)
  if fault:
    with pytest.raises(DependencyError): call()
    assert not (tmp_path / "bin/readseek").exists()
  else:
    receipt = call()
    assert receipt["platform"] == "darwin-x86_64" and receipt["native_verification"] == "not-run"
    assert receipt["license_digests"] and receipt["sdk_version"] == "15.4"
    assert (tmp_path / "bin/readseek").stat().st_mode & 0o777 == 0o700
    assert not list(tmp_path.glob(".readseek-source-*"))
