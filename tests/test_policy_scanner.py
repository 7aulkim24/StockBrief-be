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


def _run_scanner(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPOSITORY_ROOT / "scripts/check_prohibited_terms.py")],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def test_infra_scan_flags_aws_account_id_in_markdown(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "leak.md").write_text("AWS account: `999988887777`\n", encoding="utf-8")

    result = _run_scanner(tmp_path)

    assert result.returncode == 1, result.stdout
    assert "Infra-sensitive identifier policy FAILED" in result.stdout
    assert "999988887777" in result.stdout


def test_infra_scan_flags_account_id_embedded_in_bucket_name(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "bucket.md").write_text(
        "state bucket: `stockbrief-terraform-state-999988887777-ap-northeast-2`\n",
        encoding="utf-8",
    )

    result = _run_scanner(tmp_path)

    assert result.returncode == 1, result.stdout
    assert "999988887777" in result.stdout


def test_infra_scan_allows_placeholders_uuids_and_samples(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ok.md").write_text(
        "\n".join(
            [
                "AWS account: `123456789012`",
                '"source_document_id": "00000000-0000-0000-0000-000000000001"',
                "| `trading_value` | numeric | no | `888888888000` | KRW. |",
                "suppressed: 999988887777 <!-- policy-scan: allow docs-example-account -->",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run_scanner(tmp_path)

    assert result.returncode == 0, result.stdout
    assert "Infra-sensitive identifier policy passed" in result.stdout


def test_infra_scan_rejects_allow_without_reason(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "missing-reason.md").write_text(
        "suppressed: 999988887777 <!-- policy-scan: allow -->\n",
        encoding="utf-8",
    )

    result = _run_scanner(tmp_path)

    assert result.returncode == 1, result.stdout
    assert "999988887777" in result.stdout


def test_infra_scan_allows_account_id_with_reasoned_allow(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "reasoned.md").write_text(
        "suppressed: 999988887777 <!-- policy-scan: allow docs-example-account -->\n",
        encoding="utf-8",
    )

    result = _run_scanner(tmp_path)

    assert result.returncode == 0, result.stdout
    assert "Infra-sensitive identifier policy passed" in result.stdout


def test_scanner_warns_when_fe_scan_root_is_missing(tmp_path: Path) -> None:
    result = _run_scanner(tmp_path)

    assert "warning: scan root missing, skipped: ../StockBrief-fe/src" in result.stdout


def test_infra_scan_ignores_untracked_markdown_in_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "tracked.md").write_text("clean doc\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/tracked.md"], cwd=tmp_path, check=True)
    # Local-only note with an account ID stays untracked — policy targets
    # committed markdown, so this must pass.
    (docs / "local-note.md").write_text(
        "AWS account: `999988887777`\n", encoding="utf-8"
    )

    result = _run_scanner(tmp_path)

    assert result.returncode == 0, result.stdout
    assert "Infra-sensitive identifier policy passed" in result.stdout


def test_infra_scan_flags_tracked_markdown_in_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "leak.md").write_text("AWS account: `999988887777`\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/leak.md"], cwd=tmp_path, check=True)

    result = _run_scanner(tmp_path)

    assert result.returncode == 1, result.stdout
    assert "999988887777" in result.stdout
