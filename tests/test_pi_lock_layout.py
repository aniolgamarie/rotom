"""固定锁家族只选择仓库相对位置，不提供任意路径或自动回退。"""
from dataclasses import FrozenInstanceError

import pytest

from agentcfg.pi_lock_layout import dependency_layout
from agentcfg.schema import ConfigError


@pytest.mark.parametrize("profile", [None, "pi-fixture", "pi-default", "custom profile", "中文"])
def test_default_legacy_for_every_other_valid_profile(profile):
  value = dependency_layout(profile=profile)
  assert (value.family, value.lock_directory, value.dependencies_path, value.recipes_path, value.schema_version) == (
    "legacy", "locks/pi", "agents/pi/dependencies.json", "agents/pi/build/recipes.json", 1)
  with pytest.raises(FrozenInstanceError): value.lock_directory = "outside"


@pytest.mark.parametrize("profile", ["pi-base", "pi-full"])
def test_modern_profiles_use_separate_fixed_family(profile):
  value = dependency_layout(profile=profile)
  assert (value.family, value.lock_directory, value.dependencies_path, value.recipes_path, value.schema_version) == (
    "modern", "locks/pi-modern", "agents/pi/dependencies-modern.json", "agents/pi/build/recipes-modern.json", 2)
  assert dependency_layout(profile=profile, family="modern") == value


def test_explicit_modern_aggregate_and_legacy_without_profile():
  assert dependency_layout(family="modern") == dependency_layout(profile="pi-base")
  assert dependency_layout(family="legacy") == dependency_layout()


@pytest.mark.parametrize("profile,family", [("pi-base", "legacy"), ("pi-full", "legacy"), ("pi-fixture", "modern")])
def test_conflicting_family_does_not_fall_back(profile, family):
  with pytest.raises(ConfigError) as error: dependency_layout(profile=profile, family=family)
  assert error.value.code == "pi-lock-layout" and error.value.exit_code == 2


@pytest.mark.parametrize("profile", ["", ".", "..", "../synthetic-private", "pi/base", "pi\\base", "pi\nbase", "pi\0base", "pi\x7fbase", [], {}, True, 1, object()])
def test_invalid_profile_only_fixed_error(profile):
  with pytest.raises(ConfigError) as error: dependency_layout(profile=profile)
  assert error.value.code == "pi-lock-layout"
  assert "synthetic-private" not in str(error.value)


@pytest.mark.parametrize("family", ["", "unknown", "locks/pi", "../synthetic-private", [], {}, True, 2, object()])
def test_invalid_family_only_fixed_error(family):
  with pytest.raises(ConfigError) as error: dependency_layout(family=family)
  assert error.value.code == "pi-lock-layout"
  assert "synthetic-private" not in str(error.value)
