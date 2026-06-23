import uuid

from fastapi import Request

from app.models import ApiErrorResponse
from app.services.response_helpers import pagination


COMMON_ERROR_RESPONSES = {
    400: {"model": ApiErrorResponse, "description": "Request validation failed."},
    404: {"model": ApiErrorResponse, "description": "Resource was not found."},
    503: {"model": ApiErrorResponse, "description": "Upstream provider is unavailable."},
}

PROHIBITED_OUTPUTS = [
    "buy_instruction",
    "sell_instruction",
    "target_price",
    "guaranteed_return",
    "entry_price",
    "stop_loss",
]


def request_id(request: Request) -> str:
    return (
        getattr(request.state, "request_id", None)
        or request.headers.get("x-request-id")
        or f"req_{uuid.uuid4().hex}"
    )
