"""
OpenAIClient — OpenAI-compatible chat completion client.

Supports any OpenAI-compatible endpoint (OpenAI, Azure OpenAI, LMStudio, etc.)
by accepting a configurable base_url.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class OpenAIClient:
    """OpenAI-compatible chat completion client."""

    def __init__(
        self,
        provider_id: str,
        base_url: str,
        api_key: str,
        model: str,
    ) -> None:
        self.provider_id = provider_id
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    # ------------------------------------------------------------------
    # ProviderClient interface
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.0,
        response_format: dict | None = None,
        timeout: int = 240,
    ) -> str:
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "messages": messages,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        try:
            data = self._post_json(url, payload, headers, timeout=timeout)
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"OpenAI request failed: HTTP {exc.code}: {details}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenAI request failed: {exc}") from exc

        return self._extract_text(data)

    def health_check(self) -> bool:
        """Return True if the /models endpoint responds with HTTP 200."""
        url = f"{self._base_url}/models"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _post_json(
        url: str,
        payload: dict,
        headers: dict,
        timeout: int = 240,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        # Standard OpenAI chat completions response shape
        if "choices" in data and data["choices"]:
            message = data["choices"][0].get("message", {})
            content = message.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "\n".join(
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ).strip()

        # Responses API shape (some provider variants)
        if "output" in data:
            parts: list[str] = []
            for item in data["output"]:
                if not isinstance(item, dict):
                    continue
                for ci in item.get("content", []):
                    if isinstance(ci, dict) and ci.get("type") == "output_text":
                        parts.append(ci.get("text", ""))
            return "\n".join(parts).strip()

        raise ValueError(f"Could not extract text from provider response: {list(data.keys())}")
