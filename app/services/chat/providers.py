from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.models import (
    ChatResponse,
    RecommendationCandidateResponse,
    StockEvidenceItemResponse,
)
from app.services.chat.composer import compose_chat_answer


@dataclass(frozen=True)
class ChatProviderInput:
    message: str
    candidate: RecommendationCandidateResponse
    evidence: list[StockEvidenceItemResponse]


class ChatProviderUnavailable(RuntimeError):
    pass


class ChatProvider(Protocol):
    name: str

    def compose(self, request: ChatProviderInput) -> ChatResponse:
        raise NotImplementedError


class MockChatProvider:
    name = "mock"

    def compose(self, request: ChatProviderInput) -> ChatResponse:
        return compose_chat_answer(
            message=request.message,
            candidate=request.candidate,
            evidence=request.evidence,
        )


class BedrockChatProvider:
    name = "bedrock"

    def compose(self, request: ChatProviderInput) -> ChatResponse:
        raise ChatProviderUnavailable(
            "Bedrock chat provider is not enabled in this build. Use CHAT_PROVIDER=mock."
        )


def chat_provider_for(name: str) -> ChatProvider:
    if name == "mock":
        return MockChatProvider()
    if name == "bedrock":
        return BedrockChatProvider()
    raise ChatProviderUnavailable(f"Unsupported chat provider: {name}")
