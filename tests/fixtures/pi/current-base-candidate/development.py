"""仅另授权后运行的 detached npm ci；不sync/seal/activate/launch。"""
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time

MAX_LOG = 16 * 1024 * 1024


def pin(path):
  raw = path.read_bytes()
  return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def write_json(path, value):
  fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
  with os.fdopen(fd, "w") as stream:
    json.dump(value, stream, indent=2, ensure_ascii=False); stream.write("\n")


def bounded_tool(argv, *, cwd, env, evidence, phase):
  # stdout/stderr逐块写入专有槽；失败后的未退出工具仍在外层自有进程组内。
  paths = [evidence / (phase + suffix) for suffix in (".stdout", ".stderr")]
  counts = [0, 0]; started = time.time_ns(); child = None; handles = []
  selector = selectors.DefaultSelector(); failed = None; code = None
  try:
    for path in paths:
      fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
      handles.append(os.fdopen(fd, "wb"))
    child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    selector.register(child.stdout, selectors.EVENT_READ, 0)
    selector.register(child.stderr, selectors.EVENT_READ, 1)
    while selector.get_map():
      for key, _ in selector.select(0.2):
        raw = os.read(key.fileobj.fileno(), 65536)
        if not raw: selector.unregister(key.fileobj); continue
        slot = key.data
        if counts[slot] + len(raw) > MAX_LOG: raise ValueError("development tool log limit")
        handles[slot].write(raw); counts[slot] += len(raw)
    code = child.wait()
    if code != 0: raise ValueError("development tool failed")
  except BaseException as error:
    failed = type(error).__name__
    raise
  finally:
    selector.close()
    if child is not None:
      child.stdout.close(); child.stderr.close()
    for stream in handles: stream.close()
    write_json(evidence / (phase + "-result.json"), {"argv": argv, "cwd": str(cwd), "environment_names": sorted(env),
      "start_ns": started, "end_ns": time.time_ns(), "inner_exit": code, "failure_type": failed,
      "saved_bytes": counts, "log_limit_each": MAX_LOG, "logs": [str(path) for path in paths]})
  return paths[0].read_bytes().decode("utf-8", "strict").strip()


def development_steps(repository, stage, lock, evidence, env, *, run=bounded_tool):
  # 此函数以原read_lock返回值作为输入；不自行伪造完整锁或accepted binding。
  from agentcfg.pi_runtime_files import install_files
  from agentcfg.pi_license_bundle import validate_source, validate_installed
  from agentcfg.pi_vendor import install_source_licenses
  from agentcfg.storage import Tree
  piece = lock.metadata["profile_slices"]["pi-base"]
  assert lock.validated_bindings["pi-base"].state == "candidate"
  assert lock.metadata["build_steps"] == []
  assert "durable_owner" not in piece and "python_bundle" not in piece
  resolution = json.loads(lock.pairs["pi-base"][1])
  registry = validate_source(repository, piece, resolution, allow_unresolved=False)
  assert all(row["status"] != "body-scope-unresolved" for row in registry["packages"])
  with Tree(stage) as target, Tree(repository / "locks/pi-modern", private=False) as source:
    for name, raw in zip((piece["package_path"], piece["lock_path"]), lock.pairs["pi-base"]): target.write_state(name, raw)
    for identity in piece["source_ids"]:
      record = lock.metadata["sources"][identity]
      if record["kind"] not in ("local", "git"): continue
      raw = source.read(record["vendor_path"])
      assert raw is not None and hashlib.sha256(raw[0]).hexdigest() == record["archive_digest"]
      target.write_state(record["vendor_path"], raw[0])
  for name in ("node", "npm"):
    assert run([name, "--version"], cwd=stage, env=env, evidence=evidence, phase="version-"+name) == lock.metadata["toolchains"][name]
  package_root = stage / Path(piece["package_path"]).parent
  pair_paths = [stage / piece[key] for key in ("package_path", "lock_path")]
  first = [pin(path) for path in pair_paths]
  run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=package_root, env=env, evidence=evidence, phase="npm-ci")
  assert [pin(path) for path in pair_paths] == first
  install_files(repository, stage, piece["runtime_files"])
  with Tree(repository, private=False) as source, Tree(stage) as target:
    for identity in piece["source_ids"]:
      record = lock.metadata["sources"][identity]
      if record["kind"] in ("local", "git"): install_source_licenses(source, target, Path(piece["package_path"]).parent, record)
  installed_registry = validate_installed(stage, piece, resolution)
  assert [pin(path) for path in pair_paths] == first
  assert lock.validated_bindings["pi-base"].state == "candidate"
  assert not any((stage / name).exists() for name in (".agentcfg-ready", ".agentcfg-receipt.json", "current", "runtime/profile.json", "runtime/commands.json"))
  return {"identity": lock.identity, "state": "candidate", "phase": "detached npm development installation only",
    "pair_pins_before": first, "pair_pins_after": [pin(path) for path in pair_paths], "installed_license_rows": len(installed_registry["packages"]),
    "source_license_unresolved_rows": 0, "sync_seal_activate_current_host_sdk_called": False}


def main():
  repository, evidence, stage = map(Path, sys.argv[1:])
  assert repository.is_absolute() and evidence.is_absolute() and stage.is_absolute()
  assert not any(name == "agentcfg" or name.startswith("agentcfg.") for name in sys.modules)
  audit = os.open(evidence / "subprocess-audit.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
  try:
    def observe(event, args):
      if event != "subprocess.Popen": return
      executable, argv, cwd, env = args
      if type(argv) not in (tuple, list) or any(type(value) is not str for value in argv): raise RuntimeError("unexpected subprocess argv shape")
      record = {"time_ns": time.time_ns(), "executable": os.fsdecode(executable), "argv": list(argv),
        "cwd": None if cwd is None else os.fsdecode(cwd), "environment_names": None if env is None else sorted(env)}
      raw = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode()
      if os.fstat(audit).st_size + len(raw) > MAX_LOG: raise ValueError("audit log limit")
      offset = 0
      while offset < len(raw):
        count = os.write(audit, raw[offset:])
        if count <= 0: raise OSError("short audit write")
        offset += count
    sys.addaudithook(observe)
    # -I下只显式加入本次副本；agentcfg不从live仓库或旧cache取代码。
    sys.path.insert(0, str(repository / "src"))
    from agentcfg.pi_dependencies import PiBackend
    from agentcfg.pi_vendor import npm_environment
    lock = PiBackend(profile="pi-base").read_lock(repository)
    home = Path(os.environ["HOME"])
    env = npm_environment(home)
    result = development_steps(repository, stage, lock, evidence, env)
    owned = []
    for name, module in list(sys.modules.items()):
      if name != "agentcfg" and not name.startswith("agentcfg."): continue
      file = Path(module.__file__).resolve()
      assert file.is_relative_to(repository / "src")
      owned.append({"name": name, "file": str(file), **pin(file)})
    result["owned_modules"] = owned
    write_json(evidence / "producer-result.json", result)
    print(json.dumps({"state": "candidate", "installed_license_rows": result["installed_license_rows"], "no_runtime_activation": True}))
  finally:
    os.close(audit)


if __name__ == "__main__":
  main()
