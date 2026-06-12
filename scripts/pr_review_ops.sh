#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/pr_review_ops.sh request-review <pr-number|url|branch> [focus text]
  scripts/pr_review_ops.sh status [pr-number|url|branch]
  scripts/pr_review_ops.sh checks [pr-number|url|branch] [--watch]
  scripts/pr_review_ops.sh approve <pr-number|url|branch> [--yes]
  scripts/pr_review_ops.sh accept <pr-number|url|branch> [--yes]
  scripts/pr_review_ops.sh queue-auto-merge <pr-number|url|branch> --yes [--squash|--merge|--rebase]
  scripts/pr_review_ops.sh merge <pr-number|url|branch> --yes [--squash|--merge|--rebase]

Examples:
  scripts/pr_review_ops.sh request-review 42
  scripts/pr_review_ops.sh request-review 42 "security regressions and API contract drift"
  scripts/pr_review_ops.sh status 42
  scripts/pr_review_ops.sh checks 42 --watch
  scripts/pr_review_ops.sh approve 42 --yes
  scripts/pr_review_ops.sh queue-auto-merge 42 --yes --squash
  scripts/pr_review_ops.sh merge 42 --yes --squash
USAGE
}

require_gh() {
  if ! command -v gh >/dev/null 2>&1; then
    echo "GitHub CLI is required: https://cli.github.com/" >&2
    exit 1
  fi
}

confirm_or_exit() {
  local confirmed="${1:-false}"
  local message="$2"

  if [[ "$confirmed" == "true" ]]; then
    return
  fi

  printf "%s [y/N] " "$message" >&2
  read -r answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) echo "Canceled." >&2; exit 1 ;;
  esac
}

request_review() {
  local pr="${1:-}"
  if [[ -z "$pr" ]]; then
    usage
    exit 1
  fi
  shift || true

  local body="@codex review"
  if [[ "$#" -gt 0 ]]; then
    body="@codex review for $*"
  fi

  gh pr comment "$pr" --body "$body"
}

status() {
  if [[ "$#" -gt 0 ]]; then
    gh pr view "$1" \
      --json number,title,url,author,isDraft,baseRefName,headRefName,mergeStateStatus,reviewDecision,statusCheckRollup
  else
    gh pr view \
      --json number,title,url,author,isDraft,baseRefName,headRefName,mergeStateStatus,reviewDecision,statusCheckRollup
  fi
}

checks() {
  gh pr checks "$@"
}

approve() {
  local pr="${1:-}"
  if [[ -z "$pr" ]]; then
    usage
    exit 1
  fi
  shift || true

  local yes="false"
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --yes) yes="true" ;;
      *) echo "Unknown option for approve: $1" >&2; exit 1 ;;
    esac
    shift
  done

  status "$pr"
  confirm_or_exit "$yes" "Approve PR $pr after Codex review, CI checks, and P0/P1 review gate?"
  gh pr review "$pr" --approve --body "Approved after Codex review, CI checks, and P0/P1 review gate."
}

merge_pr() {
  local pr="${1:-}"
  if [[ -z "$pr" ]]; then
    usage
    exit 1
  fi
  shift || true

  local yes="false"
  local strategy="--squash"
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --yes) yes="true" ;;
      --squash|--merge|--rebase) strategy="$1" ;;
      *) echo "Unknown option for merge: $1" >&2; exit 1 ;;
    esac
    shift
  done

  if [[ "$yes" != "true" ]]; then
    echo "merge requires --yes because it changes the remote repository." >&2
    exit 1
  fi

  status "$pr"
  gh pr checks "$pr"
  confirm_or_exit "$yes" "Merge PR $pr with $strategy and delete the branch?"
  gh pr merge "$pr" "$strategy" --delete-branch
}

queue_auto_merge() {
  local pr="${1:-}"
  if [[ -z "$pr" ]]; then
    usage
    exit 1
  fi
  shift || true

  local yes="false"
  local strategy="--squash"
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --yes) yes="true" ;;
      --squash|--merge|--rebase) strategy="$1" ;;
      *) echo "Unknown option for queue-auto-merge: $1" >&2; exit 1 ;;
    esac
    shift
  done

  if [[ "$yes" != "true" ]]; then
    echo "queue-auto-merge requires --yes because it changes the remote repository." >&2
    exit 1
  fi

  status "$pr"
  gh pr checks "$pr"
  confirm_or_exit "$yes" "Add auto-merge label and enable GitHub auto-merge for PR $pr with $strategy?"
  gh label create auto-merge \
    --color 0E8A16 \
    --description "Queue PR for guarded GitHub auto-merge" \
    2>/dev/null || true
  gh pr edit "$pr" --add-label auto-merge
  gh pr merge "$pr" --auto "$strategy" --delete-branch
}

main() {
  local command="${1:-}"
  shift || true

  case "$command" in
    -h|--help|help|"") usage; return 0 ;;
    *) require_gh ;;
  esac

  case "$command" in
    request-review|review) request_review "$@" ;;
    status) status "$@" ;;
    checks) checks "$@" ;;
    approve|accept) approve "$@" ;;
    queue-auto-merge|auto-merge) queue_auto_merge "$@" ;;
    merge) merge_pr "$@" ;;
    *) echo "Unknown command: $command" >&2; usage; exit 1 ;;
  esac
}

main "$@"
