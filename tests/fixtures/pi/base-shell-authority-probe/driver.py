"""原Host constructor/run组件探针；准备不执行，guest仅合成私有账户。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


def validate_plan(plan):
  assert set(plan) == {"schema_version", "cases", "sdk_abi_only"}
  assert plan == {"schema_version": 1, "cases": ["timeout", "truncation", "fragmented-truncation"], "sdk_abi_only": False}
  return plan


def guest(preflight_only=False):
  bundle = json.loads(Path("/probe/bundle.json").read_text())
  runtime = Path("/probe/runtime") / bundle["runtime_identity"]
  sys.path[:0] = [str(runtime / "supervisor/src"), "/python-deps"]
  from agentcfg.pi_host import HostSupervisor
  from agentcfg.activity import digest, protected
  import fcntl
  state, instance, project = map(Path, ("/work/state", "/work/instance", "/work/project"))
  for path in [state, instance, instance / "pi-home", project, Path("/work/account")]: path.mkdir(parents=True, mode=0o700, exist_ok=True)
  manifest = json.loads(Path("/probe/manifest.json").read_text())
  (instance / "pi-home/agentcfg-manifest.json").write_text(json.dumps(manifest)); (instance / "pi-home/agentcfg-manifest.json").chmod(0o600)
  (project / "source.txt").write_text("own original\n"); (project / "source.txt").chmod(0o600)
  (project / "blocked.txt").write_text("hard deny sentinel\n"); (project / "blocked.txt").chmod(0o600)
  Path("/work/outside.txt").write_text("outside sentinel\n"); Path("/work/outside.txt").chmod(0o600)
  from agentcfg.pi_registered_roots import RegisteredRoots
  registered = RegisteredRoots().register(project)
  fd = os.open(state / "instance.lock", os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600); fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
  config = {"state_root": str(state), "instance_root": str(instance), "repository": str(runtime / "supervisor"), "runtime_root": str(runtime),
    "instance_id": "synthetic-base-authority", "lock_identity": bundle["lock_identity"], "slice_identity": bundle["slice_identity"],
    "policy_digest": digest(manifest["permission_policy"]), "manifest_digest": digest(manifest), "cwd": str(project), "engine": "node", "argv": ["/node/bin/node", "/probe/worker.mjs", "--guest-manager"]}
  host = HostSupervisor(config, lease_fd=fd)
  if preflight_only:
    try:
      from agentcfg.pi_shell_preparation import prepare_shell, BINDING_FIELDS
      raw = manifest["options"]["external_tools"]["shell"]
      part = prepare_shell(command_ref="tool:shell", binding={key: raw[key] for key in BINDING_FIELDS}, command="printf own", cwd=str(project), policy_generation=1,
        declared_roots=manifest["options"]["paths"]["roots"], permission_policy=manifest["permission_policy"],
        protected_roots=[str(host.root), str(host.runtime_root), str(instance), *host.config.get("protected_roots", [])])
      public = {key: part[key] for key in ("resolution", "physical")}
      plan = host._shell_backend_preflight(public)
      print(json.dumps({"status": "original-preflight-passed", "runtime_identity": plan["runtime_identity"], "helper_identity": plan["helper_identity"], "plan_digest": plan["plan_digest"]}))
      return 0
    finally: os.close(fd)
  import threading, time
  samples, stopping = [], threading.Event()
  def observe():
    deadline = time.monotonic() + 50; previous = None
    while not stopping.is_set() and time.monotonic() < deadline:
      try:
        rows = [{"lease_id": row["lease_id"], "kind": row["kind"], "state": row["state"], "protected": protected(row), "process_identity": row["process_identity"]} for row in host.store.records()]
        marker = host.store.workspaces.claims.registry.anchor / "workspace-leases" / registered["record"]["root_id"] / "write-lease.json"
        writer = json.loads(marker.read_text()) if marker.exists() else None
        snapshot = {"leases": rows, "writer": None if writer is None else {key: writer.get(key) for key in ("state", "execution_lease_id")}}
        if snapshot != previous and len(samples) < 512: samples.append(snapshot); previous = snapshot
      except (OSError, ValueError): pass
      stopping.wait(0.02)
  observer = threading.Thread(target=observe, daemon=True); observer.start()
  try:
    code = host.run()
    stopping.set(); observer.join(3)
    records = host.store.records()
    external = [row for row in records if row["kind"] == "external"]
    if code == 0:
      assert (project / "timeout-marker").read_text() == "OWN_TIMEOUT_STARTED\n"
      assert len(external) == 3 and all(not protected(row) and row["state"] == "reclaimed" for row in external)
    live_writers = []
    for lease in external:
      sequence = [sample["writer"]["state"] for sample in samples if sample["writer"] and sample["writer"]["execution_lease_id"] == lease["lease_id"]]
      live_writers.append({"lease_id": lease["lease_id"], "observed_reserved_active_released": all(state in sequence for state in ("reserved", "active", "released"))})
    diagnostic = None
    if code != 0:
      stage = "prepare-shell"
      try:
        from agentcfg.pi_shell_preparation import prepare_shell, BINDING_FIELDS
        from agentcfg.pi_shell_mounts import compile_mount_plan
        binding = {key: manifest["options"]["external_tools"]["shell"][key] for key in BINDING_FIELDS}
        part = prepare_shell(command_ref="tool:shell", binding=binding, command="printf own", cwd=str(project), policy_generation=1,
          declared_roots=manifest["options"]["paths"]["roots"], permission_policy=manifest["permission_policy"], permissions=manifest["options"].get("permissions", {}),
          protected_roots=[str(host.root), str(host.runtime_root), str(instance), *host.config.get("protected_roots", [])])
        stage = "compile-mount-plan"; compile_mount_plan({key: part[key] for key in ("resolution", "physical")})
        diagnostic = {"stage": stage, "status": "pure-check-passed"}
      except Exception as error: diagnostic = {"stage": stage, "error_type": type(error).__name__, "message": str(error)[:192]}
    result = {"pure_diagnostic": diagnostic, "host_exit": code, "protected_after_run": sum(protected(row) for row in records), "records": [{key: row.get(key) for key in ("lease_id", "kind", "state", "grant_generation", "process_identity", "planned_workspaces", "termination_evidence")} for row in records],
      "shell_marker": (project / "shell-marker").read_text() if (project / "shell-marker").exists() else None, "heartbeat_bytes": (project / "shell-heartbeat").stat().st_size if (project / "shell-heartbeat").exists() else 0,
      "blocked": (project / "blocked.txt").read_text(), "outside": Path("/work/outside.txt").read_text(), "actual_host_constructor_run": True, "live_samples": samples, "live_writer_observations": live_writers}
    Path("/work/authority-result.json").write_text(json.dumps(result))
    return code
  finally: stopping.set(); observer.join(3); os.close(fd)


if __name__ == "__main__":
  parser = argparse.ArgumentParser(allow_abbrev=False); parser.add_argument("--guest", action="store_true"); parser.add_argument("--validate-plan"); parser.add_argument("--preflight-only", action="store_true")
  args = parser.parse_args()
  if args.guest:
    try: sys.exit(guest(args.preflight_only))
    except Exception as error:
      print(json.dumps({"status": "guest-failed", "error_type": type(error).__name__, "message": str(error)[:256]})); sys.exit(2)
  if args.validate_plan: validate_plan(json.loads(Path(args.validate_plan).read_text())); print("plan-valid")
