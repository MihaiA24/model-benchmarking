from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


PROVIDER_PROTOCOL_ENV = "MODEL_BENCHMARK_PROVIDER_PROTOCOL"
ANTHROPIC_VERSION = "2023-06-01"


class ProviderProtocol(str, Enum):
    OPENAI_CHAT_COMPLETIONS = "openai-chat-completions"
    ANTHROPIC_MESSAGES = "anthropic-messages"


_EMPTY_HEADERS: Mapping[str, str] = MappingProxyType({})


@dataclass(frozen=True)
class ProviderProtocolSpec:
    endpoint_path: str
    ai_sdk_package: str
    credential_header: str
    credential_prefix: str = ""
    required_headers: Mapping[str, str] = _EMPTY_HEADERS
    trial_credential_headers: tuple[tuple[str, str], ...] = ()

    def accepted_trial_credentials(self) -> tuple[tuple[str, str], ...]:
        return self.trial_credential_headers or (
            (self.credential_header, self.credential_prefix),
        )

    def credential_value(self, credential: str) -> str:
        return self.credential_prefix + credential


PROVIDER_PROTOCOLS: Mapping[ProviderProtocol, ProviderProtocolSpec] = MappingProxyType(
    {
        ProviderProtocol.OPENAI_CHAT_COMPLETIONS: ProviderProtocolSpec(
            endpoint_path="/chat/completions",
            ai_sdk_package="@ai-sdk/openai-compatible",
            credential_header="Authorization",
            credential_prefix="Bearer ",
        ),
        ProviderProtocol.ANTHROPIC_MESSAGES: ProviderProtocolSpec(
            endpoint_path="/messages",
            ai_sdk_package="@ai-sdk/anthropic",
            credential_header="x-api-key",
            required_headers=MappingProxyType({"anthropic-version": ANTHROPIC_VERSION}),
            trial_credential_headers=(
                ("Authorization", "Bearer "),
                ("x-api-key", ""),
            ),
        ),
    }
)


def parse_provider_protocol(value: object) -> ProviderProtocol:
    if not isinstance(value, str):
        raise ValueError("provider protocol must be a string")
    try:
        return ProviderProtocol(value)
    except ValueError as error:
        raise ValueError(f"unsupported provider protocol: {value}") from error


def provider_protocol_spec(protocol: ProviderProtocol) -> ProviderProtocolSpec:
    try:
        return PROVIDER_PROTOCOLS[protocol]
    except (KeyError, TypeError) as error:
        raise ValueError(f"unsupported provider protocol: {protocol}") from error
