"""Pin the backward-compatible import surface of the split clients module.

Before the provider split, ``app.services.external.clients`` exposed the
provider clients AND the shared domain types/config it imported. External
callers and test helpers relied on both, so the thin re-export module must
keep every previously-importable domain name resolvable.
"""

import importlib


PREVIOUSLY_IMPORTABLE = (
    # provider clients + constants
    "BaseExternalApiClient",
    "OpenDartClient",
    "NaverNewsClient",
    "KrxClient",
    "OPENDART_PROVIDER",
    "NAVER_PROVIDER",
    "KRX_PROVIDER",
    # shared domain types / config that the original module re-exposed
    "Settings",
    "CompanyIdentifier",
    "ExternalApiResult",
    "ExternalRequest",
    "ExternalResponse",
    "ExternalTransport",
    "RateLimitPolicy",
    "ExternalApiCacheService",
    "ExternalApiCallLogger",
    "urllib_transport",
)


def test_clients_module_reexports_full_domain_surface() -> None:
    module = importlib.import_module("app.services.external.clients")
    missing = [name for name in PREVIOUSLY_IMPORTABLE if not hasattr(module, name)]
    assert not missing, f"clients.py dropped importable names: {missing}"


def test_star_import_exposes_domain_surface() -> None:
    namespace: dict[str, object] = {}
    exec("from app.services.external.clients import *", namespace)
    missing = [name for name in PREVIOUSLY_IMPORTABLE if name not in namespace]
    assert not missing, f"`import *` dropped names: {missing}"


def test_reexported_types_are_the_canonical_objects() -> None:
    from app.services.external import clients, types
    from app.config import Settings

    assert clients.ExternalApiResult is types.ExternalApiResult
    assert clients.RateLimitPolicy is types.RateLimitPolicy
    assert clients.Settings is Settings
