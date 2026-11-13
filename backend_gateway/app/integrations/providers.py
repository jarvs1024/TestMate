"""外部系统注册表 (PingCode / PLM)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    code: str
    name: str
    enabled: bool


PROVIDERS = (
    Provider(code="pingcode", name="PingCode", enabled=True),
    Provider(code="plm", name="PLM", enabled=True),
)

PROVIDER_BY_CODE = {provider.code: provider for provider in PROVIDERS}


def get_provider(code: str) -> Provider | None:
    return PROVIDER_BY_CODE.get(code)
