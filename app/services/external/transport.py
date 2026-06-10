from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.services.external.types import ExternalRequest, ExternalResponse


def urllib_transport(request: ExternalRequest) -> ExternalResponse:
    query = urlencode(request.params)
    url = f"{request.url}?{query}" if query else request.url
    http_request = Request(
        url=url,
        method=request.method,
        headers=request.headers,
    )
    with urlopen(http_request, timeout=request.timeout_seconds) as response:
        raw = response.read().decode("utf-8")
        payload = json.loads(raw) if raw else {}
        return ExternalResponse(status_code=response.status, payload=payload)
