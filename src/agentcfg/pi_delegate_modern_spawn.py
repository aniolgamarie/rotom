"""现代固定Pi worker的最小受管配置；不复制原生账号或沿用旧SDK入口。"""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

from .deployment import json_bytes
from .model_delegate_backends import backend_environment
from .pi_supervisor import SpawnCommand
from .process import DependencyError
from .secrets import CredentialError
from .storage import Conflict, Tree, ensure_private


def resolve_modern_delegate(host, lease, value, definition, entry):
  request = value["request"]
  if (request["backend"] != "pi" or value["retry_limit"] != 0 or value["route"]["mode"] != "direct"
      or definition["engine"] != "node" or definition["entrypoint"] != "runtime/official-delegate-worker-main.mjs"):
    raise DependencyError("DELEGATE_MODERN_TRANSPORT_UNAVAILABLE")
  manifest = host.manifest()
  provider_id, model_id = request["requested_model"]["provider_id"], request["requested_model"]["model_id"]
  binding = manifest.get("provider_bindings", {}).get(provider_id)
  provider = manifest.get("model_configuration", {}).get("providers", {}).get(provider_id)
  if (not binding or not provider or binding["auth_kind"] != "api-key" or provider["auth_kind"] != "api-key"
      or provider["owner"] != "pi-environment"):
    raise DependencyError("DELEGATE_MODERN_AUTH_UNAVAILABLE")
  scoped = deepcopy(provider)
  selected = [row for row in scoped["config"]["models"] if row["id"] == model_id]
  if len(selected) != 1: raise Conflict("DELEGATE_MODEL_UNBOUND")
  scoped["config"]["models"] = selected
  variable = "AGENTCFG_PI_CREDENTIAL_" + hashlib.sha256(provider["logical_id"].encode()).hexdigest()[:16].upper()
  with Tree(Path(host.config["instance_root"])) as tree: raw = tree.read("pi-home/models.json", max_bytes=1024 * 1024)
  if raw is None or raw[1] != 0o600: raise Conflict("DELEGATE_MODEL_CONFIGURATION_UNAVAILABLE")
  actual = json.loads(raw[0]).get("providers", {}).get(provider_id)
  expected = {**provider["config"], "apiKey": "$" + variable}
  if actual != expected: raise Conflict("DELEGATE_MODEL_CONFIGURATION_STALE")
  secret = os.environ.get(variable)
  if not secret: raise CredentialError()
  temporary = host.root / "activity/delegate-homes" / lease["lease_id"]
  ensure_private(temporary); ensure_private(temporary / "tmp")
  scoped_instance = temporary / "instance"
  with Tree(scoped_instance, create=True) as tree:
    tree.write_state("pi-home/models.json", json_bytes({"providers": {provider_id: {**scoped["config"], "apiKey": "$" + variable}}}))
  projection = {"profile_id": "pi-full", "allowed_models": [{"provider": provider_id, "model": model_id}],
    "provider_bindings": {provider_id: deepcopy(binding)}, "model_configuration": {"schema_version": 1, "providers": {provider_id: scoped}}}
  association = host.delegates.modern_attempts[request["run_id"]]
  logical = host.delegates.logical.private(association["logical_run_id"])
  worker = {"schema_version": 3, "input": value, "reports": str(host.delegates.root / "reports" / request["run_id"]),
    "runtime_root": str(host.runtime_root), "scoped_instance_root": str(scoped_instance), "scoped_manifest": projection,
    "budget": logical["budget"], "logical_run_id": logical["run_id"]}
  if request["continuation_of"]: worker["resume_source_path"] = host.delegates.modern_resume_path(request)
  with Tree(host.root) as tree:
    name = "activity/delegate-worker-inputs/" + lease["lease_id"] + ".json"
    tree.write_immutable(name, json_bytes(worker))
  env = backend_environment(home=temporary, instance=scoped_instance, route=value["route"], executable=entry, credentials={variable: secret})
  env.update(AGENTCFG_SUPERVISOR_ENDPOINT=str(host.server.endpoint),
    AGENTCFG_SUPERVISOR_CAPABILITY=host.service.issue_capability("worker", lease["lease_id"]),
    AGENTCFG_EXECUTION_LEASE_ID=lease["lease_id"], AGENTCFG_PYTHON=sys.executable,
    AGENTCFG_SUPERVISOR_CLIENT=str(host.repository / "scripts/pi-control.py"))
  engine = getattr(host, "engine_executable", None)
  if not engine or not Path(engine).is_absolute() or not Path(engine).is_file() or not os.access(engine, os.X_OK):
    raise DependencyError("DELEGATE_MODERN_ENGINE_UNAVAILABLE")
  return SpawnCommand((engine, "--experimental-import-meta-resolve", str(entry), "--input", str(host.root / name)),
    Path(request["cwd"]), env, stdin_pipe=True)
