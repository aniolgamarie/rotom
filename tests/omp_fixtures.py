"""OMP tests only: synthetic identities, assets and existing native sentinels."""

import hashlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def omp_native_home(tmp_path):
  home = tmp_path / "home"
  paths = (home / ".omp/agent", home / ".omp/profiles/existing-a/agent", home / ".omp/profiles/existing-b/agent",
           home / ".pi/agent", home / ".dsh")
  for index, path in enumerate(paths):
    path.mkdir(parents=True)
    (path / "sentinel").write_text(f"sentinel-{index}")
  return home


@pytest.fixture
def fake_omp_asset(tmp_path):
  content = b"#!/bin/sh\nexit 37\n"
  path = tmp_path / "omp"
  path.write_bytes(content)
  return path, hashlib.sha256(content).hexdigest()


@pytest.fixture
def fake_omp_process():
  calls = []
  def run(argv, *, cwd, env):
    calls.append({"argv": tuple(argv), "cwd": Path(cwd), "env": dict(env)})
    return 37
  run.calls = calls
  return run


@pytest.fixture
def omp_profiles():
  return ("omp-alpha", "omp-beta")
