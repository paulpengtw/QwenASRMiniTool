"""tests/test_ci_workflows.py — structural assertions about the CI workflow files.

Decision source: 07 (define-support-evidence).

Checks:
  - .github/workflows/ci.yml parses as valid YAML.
  - .github/workflows/scheduled-real-path.yml parses as valid YAML.
  - ci.yml defines an "ubuntu" job on ubuntu-24.04.
  - ci.yml defines a "windows" job on windows-latest.
  - ci.yml ubuntu job sets HF_HUB_OFFLINE=1 (no Hugging Face traffic on PR CI).
  - ci.yml ubuntu job has a step that runs scripts/check-requirements-sync.sh.
  - ci.yml ubuntu job has a step that runs "node --test".
  - scheduled-real-path.yml defines a cron schedule.
  - scheduled-real-path.yml is triggered by workflow_dispatch.
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="pyyaml not installed; add to dev extra")

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SCHEDULED_YML = REPO_ROOT / ".github" / "workflows" / "scheduled-real-path.yml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _steps_text(job_def: dict) -> list[str]:
    """Return a flat list of textual content from all step run/uses fields."""
    parts: list[str] = []
    for step in job_def.get("steps", []):
        for key in ("run", "uses", "name"):
            if key in step and step[key]:
                parts.append(str(step[key]))
    return parts


def _env_vars(job_def: dict) -> dict[str, str]:
    """Collect env vars from the job-level env block."""
    result: dict[str, str] = {}
    result.update(job_def.get("env", {}) or {})
    for step in job_def.get("steps", []):
        result.update(step.get("env", {}) or {})
    return result


# ---------------------------------------------------------------------------
# ci.yml — parse
# ---------------------------------------------------------------------------

class TestCiYmlParsesAsYaml:
    def test_file_exists(self):
        assert CI_YML.exists(), f"Missing: {CI_YML}"

    def test_parses_as_yaml(self):
        doc = _load_yaml(CI_YML)
        assert isinstance(doc, dict)

    def test_has_jobs_key(self):
        doc = _load_yaml(CI_YML)
        assert "jobs" in doc


# ---------------------------------------------------------------------------
# ci.yml — ubuntu job
# ---------------------------------------------------------------------------

class TestCiYmlUbuntuJob:
    @pytest.fixture(scope="class")
    def ubuntu_job(self):
        doc = _load_yaml(CI_YML)
        jobs = doc.get("jobs", {})
        assert "ubuntu" in jobs, f"No 'ubuntu' job found; got: {list(jobs)}"
        return jobs["ubuntu"]

    def test_runs_on_ubuntu_2404(self, ubuntu_job):
        runs_on = ubuntu_job.get("runs-on", "")
        assert "ubuntu-24.04" in str(runs_on), (
            f"ubuntu job must run on ubuntu-24.04; got: {runs_on!r}"
        )

    def test_hf_hub_offline_set(self, ubuntu_job):
        env = _env_vars(ubuntu_job)
        assert "HF_HUB_OFFLINE" in env, (
            "ubuntu job must set HF_HUB_OFFLINE (no Hugging Face traffic in PR CI)"
        )
        assert str(env["HF_HUB_OFFLINE"]) == "1", (
            f"HF_HUB_OFFLINE must be '1'; got: {env['HF_HUB_OFFLINE']!r}"
        )

    def test_requirements_sync_step(self, ubuntu_job):
        texts = _steps_text(ubuntu_job)
        assert any("check-requirements-sync" in t for t in texts), (
            "ubuntu job must have a step running scripts/check-requirements-sync.sh"
        )

    def test_node_test_step(self, ubuntu_job):
        texts = _steps_text(ubuntu_job)
        assert any("node --test" in t for t in texts), (
            "ubuntu job must have a step running 'node --test'"
        )


# ---------------------------------------------------------------------------
# ci.yml — windows job
# ---------------------------------------------------------------------------

class TestCiYmlWindowsJob:
    @pytest.fixture(scope="class")
    def windows_job(self):
        doc = _load_yaml(CI_YML)
        jobs = doc.get("jobs", {})
        assert "windows" in jobs, f"No 'windows' job found; got: {list(jobs)}"
        return jobs["windows"]

    def test_runs_on_windows_latest(self, windows_job):
        runs_on = windows_job.get("runs-on", "")
        assert "windows-latest" in str(runs_on), (
            f"windows job must run on windows-latest; got: {runs_on!r}"
        )

    def test_settings_store_test(self, windows_job):
        texts = _steps_text(windows_job)
        assert any("test_settings_store" in t for t in texts), (
            "windows job must run tests/test_settings_store.py"
        )

    def test_platform_seams_import_test(self, windows_job):
        texts = _steps_text(windows_job)
        assert any("test_platform_seams_import" in t for t in texts), (
            "windows job must run tests/test_platform_seams_import.py"
        )

    def test_requirements_sync_step(self, windows_job):
        texts = _steps_text(windows_job)
        assert any("check-requirements-sync" in t for t in texts), (
            "windows job must have a requirements sync step"
        )


# ---------------------------------------------------------------------------
# scheduled-real-path.yml — parse
# ---------------------------------------------------------------------------

class TestScheduledRealPathParsesAsYaml:
    def test_file_exists(self):
        assert SCHEDULED_YML.exists(), f"Missing: {SCHEDULED_YML}"

    def test_parses_as_yaml(self):
        doc = _load_yaml(SCHEDULED_YML)
        assert isinstance(doc, dict)


# ---------------------------------------------------------------------------
# scheduled-real-path.yml — triggers
# ---------------------------------------------------------------------------

class TestScheduledRealPathTriggers:
    @pytest.fixture(scope="class")
    def doc(self):
        return _load_yaml(SCHEDULED_YML)

    def test_has_cron_schedule(self, doc):
        on_block = doc.get("on", doc.get(True, {}))  # 'on' may parse as True
        assert on_block is not None, "No 'on' trigger block found"
        on_str = str(on_block)
        assert "schedule" in on_str or "cron" in on_str, (
            "scheduled-real-path.yml must define a cron schedule"
        )

    def test_has_workflow_dispatch(self, doc):
        on_block = doc.get("on", doc.get(True, {}))
        on_str = str(on_block)
        assert "workflow_dispatch" in on_str, (
            "scheduled-real-path.yml must support workflow_dispatch"
        )
