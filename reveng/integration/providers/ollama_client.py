"""
OllamaClient — Ollama via its OpenAI-compatible /v1/chat/completions endpoint.

Ollama accepts OpenAI-format requests when using the /v1 path, so the wire
protocol is identical to OpenAIClient.  The only differences are:
  - No real API key required (we send "ollama" as the token; it is ignored)
  - Health check uses Ollama's native GET /api/tags endpoint
"""
from __future__ import annotations

import urllib.request

from reveng.integration.providers.openai_client import OpenAIClient


class OllamaClient(OpenAIClient):
    """Ollama chat client via OpenAI-compatible API."""

    def __init__(self, provider_id: str, base_url: str, model: str) -> None:
        # Ollama ignores the api_key; send a dummy value
        super().__init__(
            provider_id=provider_id,
            base_url=base_url,
            api_key="ollama",
            model=model,
        )

    def health_check(self) -> bool:
        """
        Use Ollama's native GET /api/tags to verify the server is running.

        We strip the '/v1' suffix (if present) to reach the Ollama base URL.
        """
        base = self._base_url
        if base.endswith("/v1"):
            base = base[:-3]
        url = f"{base}/api/tags"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception:
            return False
