from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts/check_bedrock_chat_smoke.py"


spec = importlib.util.spec_from_file_location("check_bedrock_chat_smoke", SCRIPT_PATH)
assert spec is not None
smoke = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = smoke
spec.loader.exec_module(smoke)


class FakeBedrockClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict[str, object]] = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {"output": {"message": {"content": [{"text": self.text}]}}}


def test_bedrock_smoke_redacts_answer_and_reports_hash() -> None:
    client = FakeBedrockClient("정상 응답입니다.")

    result = smoke.run_smoke(
        model_id="apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
        region="ap-northeast-2",
        prompt="smoke",
        timeout_seconds=1,
        max_tokens=16,
        temperature=0,
        client=client,
    )

    payload = result.as_dict()
    assert payload["ok"] is True
    assert payload["answer_length"] == len("정상 응답입니다.")
    assert payload["answer_sha256_prefix"]
    assert "정상 응답입니다." not in str(payload)
    assert client.calls[0]["modelId"] == "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"


def test_bedrock_smoke_blocks_guard_terms_without_raw_answer() -> None:
    result = smoke.run_smoke(
        model_id="apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
        region="ap-northeast-2",
        prompt="smoke",
        timeout_seconds=1,
        max_tokens=16,
        temperature=0,
        client=FakeBedrockClient("매수 표현이 포함된 응답"),
    )

    payload = result.as_dict()
    assert payload["ok"] is False
    assert payload["matched_terms"] == ["매수"]
    assert "매수 표현이 포함된 응답" not in str(payload)


def test_extract_text_joins_text_blocks_only() -> None:
    result = smoke.extract_text(
        {
            "output": {
                "message": {
                    "content": [
                        {"text": " 첫 문장 "},
                        {"image": "ignored"},
                        {"text": "둘째 문장"},
                    ]
                }
            }
        }
    )

    assert result == "첫 문장\n둘째 문장"
