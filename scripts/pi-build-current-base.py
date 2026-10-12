"""私有快照的Base候选/开发安装；不发布正式锁、不sync/activate/run。"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / ".cache/pi-two-profiles/run-20261004/base-current-candidate-development-review01"
NODE = Path("/home/weixiaoxian.wxx/.nvm/versions/node/v24.14.0/bin/node")
NPM = ROOT / ".cache/pi-two-profiles/run-20261004/npm-11.19.1-tool-material-review01"
LIMIT_BYTES = 512 * 1024 * 1024
LIMIT_FILES = 12000


def pin(path):
  checksum = hashlib.sha256()
  with path.open("rb") as stream:
    while chunk := stream.read(65536): checksum.update(chunk)
  return {"bytes": path.stat().st_size, "sha256": checksum.hexdigest()}


def write(path, value):
  path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
  with path.open("x") as stream: json.dump(value, stream, indent=2, ensure_ascii=False); stream.write("\n")
  path.chmod(0o600)


def registry_rows(lock):
  # 保留原JSON键顺序与全部字段；正式固定投影另由原load_seed/validate_seed_result校验。
  return [(name, row) for name, row in lock["packages"].items() if row.get("resolved", "").startswith("https://registry.npmjs.org/")]


def prepare(name):
  run = BASE / name; run.mkdir(mode=0o700, parents=True)
  workspace = Path(tempfile.mkdtemp(prefix="pi-base-candidate-", dir="/tmp")); workspace.chmod(0o700)
  repository = workspace / "repository"; repository.mkdir(mode=0o700)
  names = set()
  for prefix in ["agents/pi", "src/agentcfg", "schemas"]:
    for directory, dirs, files in os.walk(ROOT / prefix, followlinks=False):
      dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", "__pycache__")]
      for file in files:
        p = Path(directory) / file
        if p.suffix == ".pyc": continue
        names.add(p.relative_to(ROOT).as_posix())
  for pattern in ["profiles/pi-*.toml", "scripts/pi-*.py"]:
    names.update(p.relative_to(ROOT).as_posix() for p in ROOT.glob(pattern))
  names.update(["scripts/pi-supervisor-macos.c", "scripts/pi-project-check", "pyproject.toml", "uv.lock", "shared/content.toml"])
  import tomllib
  selected = set()
  for p in ROOT.glob("profiles/pi-*.toml"): selected.update(tomllib.loads(p.read_text()).get("skills", []))
  for catalog in [ROOT / "shared/content.toml", ROOT / "agents/pi/content.toml"]:
    for key, row in tomllib.loads(catalog.read_text()).get("skills", {}).items():
      if key in selected:
        for p in (ROOT / row["path"]).rglob("*"):
          if p.is_file(): names.add(p.relative_to(ROOT).as_posix())
  # 原固定asset inputs，不复制旧manifest/pair来冒充current。
  dependencies = json.loads((ROOT / "agents/pi/dependencies-modern.json").read_text())
  for row in dependencies["sources"].values():
    if row["kind"] == "asset":
      names.add("locks/pi-modern/" + row["vendor_path"])
      if "build_record" in row:
        reference = "locks/pi-modern/" + row["build_record"]["path"]
        names.add(reference)
        record = json.loads((ROOT / reference).read_bytes())
        for item in record["inputs"].values(): names.add("locks/pi-modern/build-inputs/" + item["sha256"] + "/" + item["name"])
  rows = []; total = 0
  for name in sorted(names):
    source = ROOT / name; info = source.lstat(); assert stat.S_ISREG(info.st_mode) and not source.is_symlink()
    total += info.st_size; assert total <= LIMIT_BYTES and len(rows) < LIMIT_FILES
    target = repository / name; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    expected = pin(source); shutil.copyfile(source, target); target.chmod(0o700 if info.st_mode & 0o111 else 0o600)
    assert pin(target) == expected; rows.append({"path":name, **expected})
  tool = workspace / "tools"; shutil.copytree(NPM / "package", tool / "package")
  inventory = json.loads((NPM / "inventory.json").read_text())
  # inventory rows were already frozen; reject source or copied npm byte drift.
  inventory_rows = inventory if isinstance(inventory, list) else inventory["files"]
  for row in inventory_rows:
    p=NPM/row['path'];assert pin(p)=={k:row[k] for k in ('bytes','sha256')}
    assert pin(tool/row['path'])==pin(p)
  bindir = tool / "bin"; bindir.mkdir(mode=0o700);shutil.copyfile(NODE,bindir/"node");(bindir/"node").chmod(0o700);assert pin(bindir/"node")==pin(NODE)
  (tool / "package/bin/npm-cli.js").chmod(0o700)
  os.symlink("../package/bin/npm-cli.js", bindir / "npm")
  home=workspace/"private-home";home.mkdir(mode=0o700);tmp=workspace/"tmp";tmp.mkdir(mode=0o700)
  stage=workspace/"installed-tree";stage.mkdir(mode=0o700)
  write(run/"preparation.json",{"workspace":str(workspace),"repository":str(repository),"home":str(home),"tmp":str(tmp),"stage":str(stage),"bindir":str(bindir),"source_files":rows,"source_bytes":total,"node":pin(NODE),"npm_inventory":pin(NPM/"inventory.json")})
  print(run)


def execute(run, offline):
  # 仅隔离子driver使用snapshot agentcfg；此函数不直接导入live producer。
  preparation=json.loads((run/"preparation.json").read_text());env={"PATH":preparation["bindir"],"HOME":preparation["home"],"TMPDIR":preparation["tmp"],"TMP":preparation["tmp"],"TEMP":preparation["tmp"],"LANG":"C.UTF-8","LC_ALL":"C.UTF-8","NPM_CONFIG_FETCH_RETRIES":"1","NPM_CONFIG_FETCH_TIMEOUT":"15000"}
  if offline:env["NPM_CONFIG_OFFLINE"]="true"
  for key in ("http_proxy","https_proxy","HTTP_PROXY","HTTPS_PROXY","no_proxy","NO_PROXY"):
    if os.environ.get(key):env[key]=os.environ[key]
  driver=ROOT/"tests/fixtures/pi/current-base-candidate/producer.py"
  command=[sys.executable,"-I","-B",str(driver),str(run),"offline" if offline else "registry"]
  started=time.monotonic()
  with (run/("offline.log" if offline else "registry.log")).open("xb") as output:
    process=subprocess.Popen(command,env=env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
    try:code=process.wait(timeout=600)
    except subprocess.TimeoutExpired:
      # 只本次登记的独立child进程组，停止后仍保留失败/未知材料。
      import signal
      os.killpg(process.pid,signal.SIGTERM)
      try:code=process.wait(timeout=10)
      except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);code=process.wait(timeout=10)
  write(run/("offline.exit.json" if offline else "registry.exit.json"),{"exit_code":code,"elapsed_seconds":time.monotonic()-started})
  print(code)


if __name__=="__main__":
  parser=argparse.ArgumentParser();parser.add_argument("action",choices=["prepare","offline","registry"]);parser.add_argument("run_name")
  args=parser.parse_args()
  if args.action=="prepare":prepare(args.run_name)
  else:execute(BASE/args.run_name,args.action=="offline")
