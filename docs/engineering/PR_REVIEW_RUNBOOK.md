# PR Review Runbook

이 문서는 StockBrief 백엔드 PR을 운영자가 검토하고 수락할 때 사용하는 표준 흐름이다.

## 방향

현재 기본 방식은 repository workflow가 PR 이벤트에 맞춰 `@codex review`를 자동 호출하는 방식이다.

이 방식을 우선 사용하는 이유:

- Codex native automatic review를 켜기 전에도 repository 안에서 리뷰 호출 시점과 gate를 추적할 수 있다.
- 운영자는 반복 명령 실행자가 아니라 리뷰 프로세스 관리자로 행동한다.
- Codex 리뷰, CI, 사람 리뷰를 분리해서 P0/P1 이슈를 명확히 처리할 수 있다.
- 추후 자동화가 안정적으로 검증되면 Codex settings에서 native automatic reviews로 전환할 수 있다.

공식 Codex 문서 기준으로 Codex code review는 PR 코멘트의 `@codex review`에 반응하고, repository `AGENTS.md` 지침을 따르며, GitHub PR review 형태로 P0/P1 중심 이슈를 남긴다. 자동 리뷰는 별도 설정으로 활성화할 수 있지만, 현재 팀 운영에서는 repository workflow로 먼저 검증한다.

## 사전 조건

- GitHub CLI `gh`가 설치되어 있고 `gh auth status`가 통과해야 한다.
- 대상 repository에 Codex cloud와 code review 설정이 활성화되어 있어야 한다.
- GitHub Actions workflow permission이 PR comment 작성에 필요한 `issues: write`, `pull-requests: write`를 허용해야 한다.
- PR 작성자는 `.github/PULL_REQUEST_TEMPLATE.md`를 채워야 한다.
- PR은 draft가 아니어야 하며, 하나의 목적만 포함해야 한다.

## 자동 운영 흐름

1. 팀원이 PR을 생성한다.
2. PR 작성자가 PR Template을 작성한다.
3. `codex-pr-review` workflow가 PR template을 검사한다.
4. template gate가 통과하면 workflow가 `@codex review`를 자동 comment로 남긴다.
5. Codex 리뷰 결과를 확인한다.
6. CI checks를 확인한다.
7. P0/P1 이슈는 merge 전에 처리하거나 PR thread에 명시적으로 결론을 남긴다.
8. 운영자가 merge 가능하다고 판단하면 `auto-merge` 라벨을 붙이거나 `queue-auto-merge` 명령으로 GitHub auto-merge를 활성화한다.
9. branch protection의 required checks와 required reviews가 모두 통과하면 GitHub가 squash merge한다. 통과하지 못하면 close 또는 추가 수정 요청으로 되돌린다.

## 자동 workflow

`.github/workflows/codex-pr-review.yml`은 다음 이벤트에서 실행된다.

- PR opened
- PR reopened
- PR ready_for_review
- PR synchronize
- PR edited
- workflow_dispatch

workflow는 draft PR을 건너뛰고, PR 본문의 핵심 섹션이 비어 있으면 실패한다. 같은 head commit에 대해 이미 Codex 리뷰를 요청한 경우에는 중복 comment를 남기지 않는다.

수동 재실행이 필요하면 GitHub Actions의 `codex-pr-review` workflow에서 `workflow_dispatch`를 실행하고 PR 번호를 입력한다.

## Automation Implementation Policy

자동 workflow에서는 GitHub API를 사용하고, 사람이 직접 운영할 때는 `gh` CLI를 사용한다.

이 원칙을 사용하는 이유:

- GitHub Actions 안에서는 PR 번호, head SHA, comments, labels 같은 event context를 API로 안정적으로 다루기 쉽다.
- `pull_request_target` workflow는 repository checkout 없이 GitHub API만 사용하도록 제한해 권한 상승 리스크를 줄인다.
- 중복 Codex review comment 방지처럼 조건 분기가 필요한 로직은 shell보다 `actions/github-script`가 명확하다.
- 운영자가 직접 실행하는 fallback은 `gh pr comment`, `gh pr checks`, `gh pr merge --auto`가 가장 읽기 쉽고 디버깅하기 쉽다.

중요한 기준은 구현 수단이 아니라 PR comment trigger다. 자동 workflow와 수동 fallback 모두 최종적으로 PR에 `@codex review` comment를 남기는 방식으로 Codex 리뷰를 요청한다.

## Auto-Merge Workflow

`.github/workflows/pr-auto-merge.yml`은 `auto-merge` 라벨이 붙은 non-draft PR에 대해 GitHub auto-merge를 활성화한다.

이 workflow는 즉시 merge하지 않는다. GitHub branch protection에 설정된 required status checks와 required reviews가 모두 통과해야 실제 merge가 일어난다.

운영 방식:

1. Codex 리뷰와 CI checks를 확인한다.
2. 남은 P0/P1 이슈가 없고 PR scope가 안전하면 `auto-merge` 라벨을 붙인다.
3. `pr-auto-merge` workflow가 `gh pr merge --auto --squash --delete-branch`를 실행한다.
4. GitHub가 required gate 통과 후 자동 squash merge한다.

필수 repository 설정:

- Repository Settings에서 auto-merge를 허용한다.
- `main` branch protection을 활성화한다.
- `backend-ci`의 required status checks를 지정한다.
- 최소 1개 이상의 required approving review를 요구한다.
- Squash merge를 기본 merge 방식으로 사용한다.

## 수동 fallback

workflow가 실패했거나 특정 초점으로 재검토가 필요하면 `scripts/pr_review_ops.sh`를 사용한다.

```bash
# Codex 리뷰 호출
scripts/pr_review_ops.sh request-review 42

# 특정 초점으로 Codex 리뷰 호출
scripts/pr_review_ops.sh request-review 42 "security regressions and API contract drift"

# PR 상태 확인
scripts/pr_review_ops.sh status 42

# CI checks 확인
scripts/pr_review_ops.sh checks 42 --watch

# Codex 리뷰, CI, P0/P1 gate 확인 후 승인
scripts/pr_review_ops.sh approve 42 --yes

# auto-merge 라벨 추가 및 GitHub auto-merge 활성화
scripts/pr_review_ops.sh queue-auto-merge 42 --yes --squash

# 승인 후 병합. 원격 repository를 변경하므로 --yes가 필수다.
scripts/pr_review_ops.sh merge 42 --yes --squash
```

## 승인 기준

Approve는 다음 조건을 모두 만족할 때만 한다.

- PR template의 요약, 배경, 주요 변경 사항, 테스트, 리스크, 롤백 계획이 채워져 있다.
- Codex 리뷰에 남은 P0/P1 이슈가 없다.
- CI checks가 성공했거나, 실패한 항목의 이유와 예외 판단이 PR thread에 기록되어 있다.
- 백엔드 변경은 관련 `pytest` 또는 더 좁은 검증 명령을 통과했다.
- API 계약 변경은 `docs/engineering/API_CONTRACT.md`에 반영되어 있다.
- 비밀값, credentials, private data가 포함되지 않았다.
- 금융 문구 정책과 추천 후보 표현 규칙을 위반하지 않는다.
- 운영자가 `auto-merge` 라벨을 붙이기 전에 PR thread에 예외 판단이나 남은 리스크가 기록되어 있다.

## Native automatic review 전환 기준

Codex native automatic reviews는 다음 조건이 누적되기 전까지 켜지 않는다.

- 최소 5개 이상의 PR에서 `codex-pr-review` workflow 흐름이 문제 없이 반복되었다.
- Codex 리뷰의 P0/P1 신호가 팀 리뷰 기준과 크게 어긋나지 않았다.
- PR 작성자와 운영자가 리뷰 호출 시점, CI 확인, merge gate를 일관되게 지켰다.
- native automatic reviews가 noise를 늘리지 않는다는 팀 합의가 있다.

## 문제 해결

- Codex가 반응하지 않으면 workflow가 남긴 PR comment에 `@codex review`가 포함되어 있는지 확인한다.
- repository의 Codex code review 설정과 Codex cloud 설정을 확인한다.
- `codex-pr-review` workflow가 permission 오류로 실패하면 repository Actions workflow permissions를 확인한다.
- `gh` 명령이 실패하면 `gh auth status`와 repository 권한을 먼저 확인한다.
- CI가 pending 상태면 merge하지 말고 `scripts/pr_review_ops.sh checks <pr> --watch`로 완료를 기다린다.
