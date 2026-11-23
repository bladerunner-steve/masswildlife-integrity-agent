"""Static checks for the scheduling scripts (run_daily.ps1, run_daily.sh, register_task.ps1, launchd plist).
They don't run the scripts; the scripts were exercised manually against the test vault at Checkpoint 6.
AI-assisted (Claude)."""
import os
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
S = REPO / "scripts"


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell parser")
@pytest.mark.parametrize("name", ["run_daily.ps1", "register_task.ps1"])
def test_powershell_scripts_parse(name):
    cmd = ("$e=$null; [System.Management.Automation.Language.Parser]::ParseFile("
           f"'{S / name}', [ref]$null, [ref]$e) | Out-Null; $e.Count")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "0", out.stdout + out.stderr


def _bash():
    for c in (shutil.which("bash"), r"C:\Program Files\Git\bin\bash.exe"):
        if c and Path(c).is_file() and "System32" not in c:
            return c
    return None


@pytest.mark.skipif(_bash() is None, reason="bash not available")
def test_bash_script_parses():
    r = subprocess.run([_bash(), "-n", str(S / "run_daily.sh")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_defaults_are_production_and_commands_match_spec():
    ps = (S / "run_daily.ps1").read_text(encoding="utf-8")
    sh = (S / "run_daily.sh").read_text(encoding="utf-8")
    assert '[string]$Vault = "prod"' in ps and '[string]$Db = "prod"' in ps
    assert 'VAULT="${MWIA_VAULT:-prod}"' in sh and 'DB="${MWIA_DB:-prod}"' in sh
    for text in (ps, sh):
        assert '"agent", "run"' in text or "agent run --vault" in text
        assert "verify" in text and "agent-" in text and "activate" in text.lower()
    assert "-StartWhenAvailable" in (S / "register_task.ps1").read_text(encoding="utf-8")
    assert "IgnoreNew" in (S / "register_task.ps1").read_text(encoding="utf-8")


def test_launchd_plist_is_valid_and_runs_the_daily_script():
    with open(S / "launchd" / "org.masswildlife-integrity-agent.daily.plist", "rb") as f:
        p = plistlib.load(f)
    assert p["ProgramArguments"][-1].endswith("scripts/run_daily.sh")
    assert p["StartCalendarInterval"] == {"Hour": 6, "Minute": 0}
