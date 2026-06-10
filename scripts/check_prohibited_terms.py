#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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


@dataclass(frozen=True)
class Violation:
    path: Path
    line_number: int
    term: str
    line: str


def main() -> int:
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
        print("Prohibited financial wording policy failed.")
        print("These terms must not appear in user-facing copy or AI output paths.")
        for violation in violations:
            print(
                f"- {violation.path}:{violation.line_number}: "
                f"term={violation.term!r} line={violation.line!r}"
            )
        return 1

    print("Prohibited financial wording policy passed.")
    return 0


def iter_scanned_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        if not root.exists():
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
