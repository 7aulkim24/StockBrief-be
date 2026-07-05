#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.services.chat.providers import PROHIBITED_MODEL_OUTPUT_TERMS


DEFAULT_MODEL_ID = "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"
DEFAULT_PROMPT = (
    "한국어로 한 문장만 답하세요. "
    "StockBrief Bedrock chat provider smoke check."
)


@dataclass(frozen=True)
class SmokeResult:
    ok: bool
    model_id: str
    region: str
    answer_length: int
    answer_sha256_prefix: str
    matched_terms: tuple[str, ...]
    error_code: str | None = None
    error_message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "model_id": self.model_id,
            "region": self.region,
            "answer_length": self.answer_length,
            "answer_sha256_prefix": self.answer_sha256_prefix,
            "matched_terms": list(self.matched_terms),
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_smoke(
        model_id=args.model_id,
        region=args.region,
        prompt=args.prompt,
        timeout_seconds=args.timeout_seconds,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Call Bedrock Converse once and print a redacted smoke result."
    )
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--region", default="ap-northeast-2")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--timeout-seconds", type=float, default=8.0)
    parser.add_argument("--max-tokens", type=int, default=48)
    parser.add_argument("--temperature", type=float, default=0.0)
    return parser.parse_args(argv)


def run_smoke(
    *,
    model_id: str,
    region: str,
    prompt: str,
    timeout_seconds: float,
    max_tokens: int,
    temperature: float,
    client: Any | None = None,
) -> SmokeResult:
    try:
        bedrock = client or boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=Config(
                connect_timeout=timeout_seconds,
                read_timeout=timeout_seconds,
                retries={"max_attempts": 1, "mode": "standard"},
            ),
        )
        response = bedrock.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
        )
        answer = extract_text(response)
    except (BotoCoreError, ClientError) as exc:
        return SmokeResult(
            ok=False,
            model_id=model_id,
            region=region,
            answer_length=0,
            answer_sha256_prefix="",
            matched_terms=(),
            error_code=type(exc).__name__,
            error_message=str(exc),
        )

    matched_terms = tuple(term for term in PROHIBITED_MODEL_OUTPUT_TERMS if term in answer)
    return SmokeResult(
        ok=bool(answer) and not matched_terms,
        model_id=model_id,
        region=region,
        answer_length=len(answer),
        answer_sha256_prefix=hashlib.sha256(answer.encode("utf-8")).hexdigest()[:12],
        matched_terms=matched_terms,
        error_code=None if answer else "empty_answer",
        error_message=None if answer else "Bedrock returned an empty answer.",
    )


def extract_text(response: dict[str, Any]) -> str:
    content = response.get("output", {}).get("message", {}).get("content", [])
    return "\n".join(
        item["text"].strip()
        for item in content
        if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip()
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
