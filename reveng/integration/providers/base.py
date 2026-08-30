"""
ProviderClient protocol and ProviderRegistry.

Adding a new provider means:
  1. Write a class that satisfies the ProviderClient Protocol.
  2. Add its `kind` string to factory.build_provider_client().
  3. No existing code changes.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ProviderClient(Protocol):
    """
    Minimal interface all provider implementations must satisfy.

    provider_id identifies the endpoint (e.g. "openai", "ollama").
    model is the specific model string (e.g. "gpt-4o", "llama3.2").
    """

    provider_id: str
    model: str

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.0,
        response_format: dict | None = None,
        timeout: int = 240,
    ) -> str:
        """
        Post a chat completion and return the assistant content as a plain string.

        messages: list of {"role": "...", "content": "..."} dicts.
        Never raises for model-level errors — returns an error string instead.
        Raises RuntimeError only for network/auth failures.
        """
        ...

    def health_check(self) -> bool:
        """Return True if the provider endpoint is reachable.  Never raises."""
        ...


class ProviderRegistry:
    """In-process registry mapping provider_id → ProviderClient instance."""

    def __init__(self) -> None:
        self._clients: dict[str, ProviderClient] = {}

    def register(self, client: ProviderClient) -> None:
        self._clients[client.provider_id] = client

    def get(self, provider_id: str) -> ProviderClient | None:
        return self._clients.get(provider_id)

    def get_or_raise(self, provider_id: str) -> ProviderClient:
        client = self.get(provider_id)
        if client is None:
            available = list(self._clients.keys())
            raise KeyError(
                f"Provider '{provider_id}' not registered. "
                f"Available: {available}"
            )
        return client

    def list_ids(self) -> list[str]:
        return list(self._clients.keys())

    def health_status(self) -> dict[str, bool]:
        """Return {provider_id: is_healthy} for all registered providers."""
        return {pid: client.health_check() for pid, client in self._clients.items()}
