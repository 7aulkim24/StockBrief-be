import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_prohibited_wording_scanner_passes_repository_copy() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_prohibited_terms.py"],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "policy passed" in result.stdout


def test_policy_scanner_targets_multi_repository_paths() -> None:
    scanner = (REPOSITORY_ROOT / "scripts/check_prohibited_terms.py").read_text(
        encoding="utf-8"
    )

    assert 'Path("app")' in scanner
    assert 'Path("docs")' in scanner
    assert 'Path("../StockBrief-fe/src")' in scanner
    assert "apps/web" not in scanner
    assert "services/api" not in scanner
