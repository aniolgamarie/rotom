import pytest

from agentcfg.omp import OmpAdapter
from agentcfg.omp_identity import native_identity
from agentcfg.storage import Tree, ensure_private
from agentcfg.schema import ConfigError

from test_omp_adapter import REPO, omp_data


def test_capture_allows_only_theme_keybindings_and_unique_model_roles():
  data = omp_data()
  data["profile"]["agent_options"].update(resources={"themes": ["rotom-dark"], "prompts": []},
    ui={"theme_dark": "rotom-dark", "theme_light": "rotom-dark", "keybindings": {
      "app.model.cycleForward": "Ctrl+P", "app.history.search": []}})
  projection = {"theme": {"dark": "rotom-dark", "light": "rotom-dark"},
    "keybindings": {"app.model.cycleForward": "Ctrl+P", "app.history.search": []},
    "modelRoles": {"default": "gateway/large-v1", "smol": "gateway/small-v1"}}
  proposal = OmpAdapter(REPO).capture_configuration(projection, data)
  assert proposal == {"agent_options": {"ui": {"theme_dark": "rotom-dark", "theme_light": "rotom-dark",
    "keybindings": projection["keybindings"]}}, "roles": {"main": "large", "smol": "small"}}


def test_capture_drops_auth_session_logs_cache_and_unknown_actions():
  data = omp_data()
  projection = {"auth": "SECRET_SENTINEL", "session": "SECRET_SENTINEL", "logs": "SECRET_SENTINEL",
    "cache": "SECRET_SENTINEL", "keybindings": {"unknown.action": "SECRET_SENTINEL"}}
  result = OmpAdapter(REPO).capture_configuration(projection, data)
  assert "SECRET_SENTINEL" not in repr(result)


def test_capture_projection_reads_only_allowlisted_native_preferences(tmp_path):
  instance = tmp_path / "instance"
  ensure_private(instance)
  identity = native_identity("omp-validation", instance)
  identity.agent_dir.mkdir(parents=True, mode=0o700)
  (identity.agent_dir / "config.yml").write_text(
    "theme:\n  dark: rotom-dark\n  light: rotom-dark\nmodelRoles:\n  default: gateway/large-v1\nauth:\n  token: SECRET_SENTINEL\n")
  (identity.agent_dir / "keybindings.yml").write_text(
    "app.model.cycleForward: Ctrl+P\napp.history.search: []\nunknown.action: SECRET_SENTINEL\n")
  (identity.agent_dir / "session.json").write_text("SECRET_SENTINEL")
  with Tree(instance) as tree:
    projection = OmpAdapter(REPO).capture_projection(tree)
  assert projection["theme"] == {"dark": "rotom-dark", "light": "rotom-dark"}
  assert projection["modelRoles"] == {"default": "gateway/large-v1"}
  assert projection["keybindings"] == {"app.model.cycleForward": "Ctrl+P", "app.history.search": []}
  assert "SECRET_SENTINEL" not in repr(projection)


@pytest.mark.parametrize("kind", ["undeclared", "ambiguous", "unselected"])
def test_capture_rejects_model_role_without_unique_selected_reverse_mapping(kind):
  data = omp_data()
  value = "gateway/missing"
  if kind == "ambiguous":
    data["models"]["duplicate"] = dict(data["models"]["large"])
    data["profile"]["models"].append("duplicate")
    value = "gateway/large-v1"
  elif kind == "unselected":
    data["models"]["unselected"] = {"provider": "gateway", "remote_id": "outside-v1", "input": ["text"],
      "context_window": 1, "max_output_tokens": 1}
    value = "gateway/outside-v1"
  with pytest.raises(ConfigError, match="capture-model"):
    OmpAdapter(REPO).capture_configuration({"modelRoles": {"default": value}}, data)
