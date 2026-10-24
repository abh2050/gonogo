import subprocess
from pathlib import Path

import pytest

from gonogo import aws
from gonogo.paths import ROOT


def test_settings_load_and_pin_region() -> None:
    s = aws.load_settings()
    assert s.profile == "awsnew" and s.region == "us-east-2"
    assert s.deploy_neptune is False and s.deploy_fargate is False


@pytest.mark.parametrize("region", ["us-east-1", "us-west-2", "eu-west-1", None])
def test_region_guard_rejects_other_regions(region: str | None) -> None:
    with pytest.raises(aws.RegionNotAllowedError):
        aws.check_region(region)


def test_pick_claude_profile_uses_newest_in_family(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GONOGO_CLAUDE_PROFILE", raising=False)
    profiles = [
        {"inferenceProfileId": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"},
        {"inferenceProfileId": "global.anthropic.claude-sonnet-5-5"},
        {"inferenceProfileId": "us.anthropic.claude-sonnet-5-5"},
        {"inferenceProfileId": "us.anthropic.claude-haiku-5-5"},
        {"inferenceProfileId": "eu.anthropic.claude-sonnet-9"},
        {"inferenceProfileId": "us.anthropic.claude-sonnet-6", "status": "INACTIVE"},
    ]
    assert aws.pick_claude_profile(profiles, family="sonnet") == "us.anthropic.claude-sonnet-5-5"
    assert aws.pick_claude_profile(profiles, family="haiku") == "us.anthropic.claude-haiku-5-5"
    monkeypatch.setenv("GONOGO_CLAUDE_PROFILE", "us.anthropic.claude-opus-5-5")
    assert aws.pick_claude_profile(profiles) == "us.anthropic.claude-opus-5-5"


def test_profile_version_ignores_date_suffix() -> None:
    assert aws.profile_version("us.anthropic.claude-sonnet-4-20250514-v1:0") == ("sonnet", 4, 0)
    assert aws.profile_version("us.anthropic.claude-opus-4-1-20250805-v1:0") == ("opus", 4, 1)


def test_expired_session_is_reported() -> None:
    class Expired(Exception):
        response = {"Error": {"Code": "ExpiredToken"}}

    with pytest.raises(aws.ExpiredSessionError, match="aws login"):
        aws.raise_if_expired(Expired("boom"))
    aws.raise_if_expired(ValueError("unrelated"))


def test_no_denied_region_names_outside_region_log() -> None:
    """The SCP denies us-east-1 and us-west-2. Only the status log and this test may name them."""
    files = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    if not files:
        files = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and ".venv" not in p.parts]
    allowed = {"docs/status.md", "tests/unit/test_aws.py", "gonogo/aws.py", "config/aws.yaml"}
    offenders = []
    for name in files:
        path = Path(ROOT / name)
        if (
            name in allowed
            or not path.is_file()
            or path.suffix not in {".py", ".md", ".yaml", ".yml", ".json", ".toml", ".sh"}
        ):
            continue
        if "data/" in name:
            continue
        text = path.read_text(errors="ignore")
        if "us-east-1" in text or "us-west-2" in text:
            offenders.append(name)
    assert offenders == []
