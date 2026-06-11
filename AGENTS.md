# AGENTS.md — StockBrief-be

This file defines how Codex and other agents must work in the StockBrief-be repository.

## Role

- Act as a practical senior backend engineer.
- Prefer direct action when the request is clear and low risk.
- Keep explanations concise, grounded in checked files or tool output, and explicit about unknowns.
- Do not claim completion until requested deliverables exist and relevant verification has been run.

## Repository Scope

`StockBrief-be` covers FastAPI, DB, API 계약, 테스트, 인프라 연동.

```text
.
├── app/              # FastAPI application
│   ├── services/     # Recommendation engine, chat, external adapters
│   └── seed/         # Mock seed data
├── tests/            # pytest test suite
├── migrations/       # Alembic DB migrations
├── infra/terraform/  # AWS infrastructure as code
├── scripts/          # Utility and packaging scripts
├── docs/engineering/ # API contract, DB schema, score engine, AI safety policy
├── alembic.ini
└── pyproject.toml
```

## Project Identity

StockBrief is a Korean domestic stock candidate recommendation service.

The product recommends stocks as candidates for further user review based on public evidence. It must not provide buy or sell instructions, target prices, entry prices, stop-loss prices, guaranteed returns, portfolio allocation advice, or certainty-based claims.

## Product Rules

- Use recommendation language only as `검토 후보 추천`.
- Allowed wording includes `추천 후보`, `추천 이유`, and `오늘의 추천 후보`.
- Do not use prohibited user-facing wording:
  - `매수 추천`
  - `매도 추천`
  - `목표가`
  - `진입가`
  - `손절가`
  - `수익 보장`
  - `확실`
  - `무조건`
- Every recommendation candidate must show score, reasons, evidence, data freshness, missing data status, and risk tags.
- If evidence is missing or stale, say evidence is insufficient or confirmation is required.
- AI may explain precomputed recommendations and evidence.
- AI must not generate its own investment score.

## API Contract Rules

- All public API paths start with `/v1`.
- Recommendation API path is `/v1/recommendations/candidates`.
- Include `evidence_level`, `evidence_count`, `missing_data`, and `data_freshness` in recommendation responses.
- Use deterministic score calculation. Do not call an LLM for scoring.

Score engine components:

| Component | Weight |
| --- | ---: |
| `financial_stability` | 20 |
| `profitability` | 15 |
| `growth` | 15 |
| `valuation` | 10 |
| `news_attention` | 10 |
| `disclosure_event` | 10 |
| `liquidity` | 10 |
| `momentum_volatility` | 10 |

## GitHub Operating Rules

- Treat GitHub Issue as the source of truth for scope, acceptance criteria, and review context.
- Start every task from `main`, create a short-lived branch, and keep the branch name aligned with the issue.
- Use `feat/<issue>-<slug>`, `fix/<issue>-<slug>`, `docs/<slug>`, `test/<issue>-<slug>`, `chore/<issue>-<slug>`, or `release/<version>`.
- Do not push directly to `main`. Use PRs only.
- One PR must have one purpose. Split unrelated code, docs, tests, and infra changes into separate PRs when practical.
- Link the GitHub Issue in the branch, commit messages when useful, and PR body.
- Prefer squash merge unless the reviewer or repo maintainer explicitly asks for another merge strategy.
- Keep branches short-lived. Rebase or merge `main` into the branch only when needed to resolve drift.

## PR And Review Rules

- Write PRs with: summary, background, main changes, tests run, risk/impact, rollback plan, and linked Issue.
- For backend work, include the exact commands run and their result in the PR body.
- When API behavior changes, update the corresponding API contract docs and call out BE/FE impact explicitly.
- Before requesting review, self-check for missing tests, regression risk, secret leakage, prohibited financial wording, and contract drift.
- When reviewing a PR, prioritize correctness, regressions, security, API compatibility, and test coverage over style.
- Use `Request changes` only for blocking issues. Use `Comment` for non-blocking follow-ups. Approve only when the branch is safe to merge.
- After review feedback, either address it in the same branch or explain why it is out of scope in the PR thread.

## Safety Rules For AI And Chat

- Refuse or redirect requests for buy/sell instructions, target prices, entry prices, stop-loss prices, guaranteed returns, or portfolio allocation advice.
- Use neutral wording such as `검토해볼 수 있습니다`, `확인이 필요합니다`, and `공개 데이터 기준입니다`.
- Cite or reference available evidence IDs and source URLs from API responses.
- Do not invent evidence, scores, sources, or freshness timestamps.

## Branch Policy (가이드 기준)

- Follow the GitHub Operating Rules above for branch naming, PR scope, and merge style.

## Coding Rules

- Prefer small, focused changes.
- Read existing files before editing them.
- Respect existing code style and structure.
- Add or update tests for changed behavior.
- Do not commit secrets, API keys, tokens, credentials, or private data.
- Keep `.env.example` updated when environment variables change.
- Avoid broad refactors unless requested.
- Do not add new production dependencies without a clear need.

## Verification Rules

- Backend changes: run relevant tests before completion.
- Documentation-only changes: verify file presence and scan changed docs for prohibited wording context.
- API contract changes: update `docs/engineering/API_CONTRACT.md` in the same PR.

## Definition Of Done

A task is done only when:

1. Every requested deliverable exists.
2. Code compiles when code was changed.
3. Relevant tests pass (`pytest`).
4. API contracts are documented or typed when touched.
5. No prohibited financial wording appears in user-facing copy.
6. New environment variables are added to `.env.example`.
7. Remaining limitations or skipped verification are stated in the final response.

## Default Close-Out

Final responses should include:

- What changed.
- Files or artifacts created or modified.
- Verification performed.
- Remaining limitations, if any.
