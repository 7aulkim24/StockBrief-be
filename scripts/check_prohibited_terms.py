#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


# ── Financial wording ──────────────────────────────────────────────────────────

PROHIBITED_TERMS = [
    "매수 추천",
    "매도 추천",
    "목표가",
    "진입가",
    "손절가",
    "수익 보장",
    "무조건",
    "확실한 수익",
]

SCAN_ROOTS = [
    Path("app"),
    Path("docs"),
    Path("../StockBrief-fe/src"),
    Path("../StockBrief-fe/docs"),
]

SKIP_DIRS = {
    ".next",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
}

TEXT_SUFFIXES = {
    ".css",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".ts",
    ".tsx",
    ".txt",
}

DOC_POLICY_CONTEXT = (
    "Allowed wording",
    "Prohibited",
    "prohibited",
    "Prompt Guardrails",
    "Safety",
    "Financial Wording",
    "Out Of Scope",
    "must not",
    "금지",
)

# ── Infra-sensitive identifier scan ────────────────────────────────────────────
# AWS account IDs must not appear in any committed markdown file.
# Pattern-based so the scanner never has to carry a leaked value itself,
# and so it keeps working when the team switches AWS accounts.
# UUIDs are scrubbed from each line first so their trailing 12-hex-digit
# segment ("...-0000-000000000001") is not mistaken for an account ID, while
# hyphen-embedded account IDs (e.g. state bucket names) are still caught.
AWS_ACCOUNT_ID_PATTERN = re.compile(r"(?<!\d)\d{12}(?!\d)")
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

# Always-allowed tokens: canonical AWS docs placeholders plus repo doc
# sample values that happen to be 12 digits (e.g. KRW amounts).
PLACEHOLDER_ACCOUNT_IDS = {
    "123456789012",
    "000000000000",
    "888888888000",  # DB_SCHEMA.md trading_value sample (KRW)
}

INFRA_SCAN_ROOT = Path(".")
INFRA_SCAN_SUFFIXES = {".md"}

# Fallback walk (non-git checkouts only) still skips these.
INFRA_SKIP_DIRS = {
    ".git",
    ".next",
    ".pytest_cache",
    ".terraform",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}


@dataclass(frozen=True)
class Violation:
    path: Path
    line_number: int
    term: str
    line: str


@dataclass(frozen=True)
class InfraViolation:
    path: Path
    line_number: int
    term: str
    line: str


def main() -> int:
    exit_code = 0

    violations: list[Violation] = []
    for path in iter_scanned_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            for term in PROHIBITED_TERMS:
                if term not in line:
                    continue
                if is_allowed(path, lines, index):
                    continue
                violations.append(
                    Violation(
                        path=path,
                        line_number=index + 1,
                        term=term,
                        line=line.strip(),
                    )
                )

    if violations:
        print("Prohibited financial wording policy FAILED.")
        print("These terms must not appear in user-facing copy or AI output paths.")
        for v in violations:
            print(f"- {v.path}:{v.line_number}: term={v.term!r} line={v.line!r}")
        exit_code = 1
    else:
        print("Prohibited financial wording policy passed.")

    infra_violations = scan_infra_terms()
    if infra_violations:
        print("Infra-sensitive identifier policy FAILED.")
        print("AWS account IDs must not appear in committed markdown files.")
        print("Replace with the 123456789012 placeholder, or move the content")
        print("to a local-only file covered by .gitignore.")
        for v in infra_violations:
            print(f"- {v.path}:{v.line_number}: term={v.term!r} line={v.line!r}")
        exit_code = 1
    else:
        print("Infra-sensitive identifier policy passed.")

    return exit_code


def _tracked_markdown_paths() -> list[Path] | None:
    """Markdown files tracked by git — the policy targets committed docs only.

    Returns None outside a git checkout so the caller can fall back to a
    filesystem walk (used by scanner self-tests running in temp dirs).
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.md"],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return [
        Path(entry)
        for entry in result.stdout.decode("utf-8").split("\0")
        if entry
    ]


def _fallback_markdown_paths() -> list[Path]:
    return [
        path
        for path in sorted(INFRA_SCAN_ROOT.rglob("*"))
        if path.is_file()
        and path.suffix in INFRA_SCAN_SUFFIXES
        and not any(part in INFRA_SKIP_DIRS for part in path.parts)
    ]


def scan_infra_terms() -> list[InfraViolation]:
    violations: list[InfraViolation] = []
    paths = _tracked_markdown_paths()
    if paths is None:
        print("warning: not a git checkout; scanning all markdown files")
        paths = _fallback_markdown_paths()
    for path in sorted(paths):
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if "policy-scan: allow" in line:
                continue
            scrubbed = UUID_PATTERN.sub("", line)
            for token in AWS_ACCOUNT_ID_PATTERN.findall(scrubbed):
                if token in PLACEHOLDER_ACCOUNT_IDS:
                    continue
                violations.append(
                    InfraViolation(
                        path=path,
                        line_number=index + 1,
                        term=token,
                        line=line.strip(),
                    )
                )
    return violations


def iter_scanned_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            print(f"warning: scan root missing, skipped: {root}")
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix not in TEXT_SUFFIXES:
                continue
            files.append(path)
    return sorted(files)


def is_allowed(path: Path, lines: list[str], index: int) -> bool:
    line = lines[index]
    if "policy-scan: allow" in line:
        return True
    if path.match("app/services/chat/composer.py") and _near_policy_scan_allow(lines, index):
        return True
    if "docs" in path.parts:
        return _is_documented_policy_context(lines, index)
    return False


def _near_policy_scan_allow(lines: list[str], index: int) -> bool:
    start = max(0, index - 6)
    end = min(len(lines), index + 2)
    return any("policy-scan: allow" in lines[item] for item in range(start, end))


def _is_documented_policy_context(lines: list[str], index: int) -> bool:
    start = max(0, index - 20)
    context = "\n".join(lines[start : index + 1])
    return any(token in context for token in DOC_POLICY_CONTEXT)


if __name__ == "__main__":
    raise SystemExit(main())
