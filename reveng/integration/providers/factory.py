"""
Provider factory — construct a ProviderClient from a ProviderRecord or from env vars.

Adding a new provider kind:
  1. Write a class implementing the ProviderClient protocol.
  2. Add an elif branch below.
  That's it.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from reveng.integration.providers.base import ProviderClient
from reveng.integration.providers.ollama_client import OllamaClient
from reveng.integration.providers.openai_client import OpenAIClient


def build_provider_client(
    record: Any,
    env_values: dict[str, str],
    default_model: str = "gpt-4o-mini",
) -> ProviderClient:
    """
    Construct and return a ProviderClient for the given ProviderRecord.

    *env_values* is the result of load_env_file() — used as a fallback after
    os.environ so that keys set in the environment always take precedence.
    *default_model* is used when the calling code doesn't specify a model.
    """
    api_key = ""
    if record.api_key_env:
        api_key = os.environ.get(
            record.api_key_env,
            env_values.get(record.api_key_env, ""),
        )

    model = os.environ.get("OPENAI_MODEL", env_values.get("OPENAI_MODEL", default_model))

    if record.kind == "openai":
        return OpenAIClient(
            provider_id=record.id,
            base_url=record.base_url,
            api_key=api_key,
            model=model,
        )
    elif record.kind == "ollama":
        return OllamaClient(
            provider_id=record.id,
            base_url=record.base_url,
            model=model,
        )
    else:
        raise ValueError(
            f"Unknown provider kind '{record.kind}' for provider '{record.id}'. "
            "Add a new branch to integration/providers/factory.py."
        )


def build_provider_client_for_agent(
    record: Any,
    agent_model: str,
    env_values: dict[str, str],
) -> ProviderClient:
    """
    Construct a ProviderClient using the specific model requested by an agent.

    This is the version that should be called when executing an agent run,
    so the agent's model choice is respected rather than the env default.
    """
    api_key = ""
    if record.api_key_env:
        api_key = os.environ.get(
            record.api_key_env,
            env_values.get(record.api_key_env, ""),
        )

    if record.kind == "openai":
        return OpenAIClient(
            provider_id=record.id,
            base_url=record.base_url,
            api_key=api_key,
            model=agent_model,
        )
    elif record.kind == "ollama":
        return OllamaClient(
            provider_id=record.id,
            base_url=record.base_url,
            model=agent_model,
        )
    else:
        raise ValueError(f"Unknown provider kind: {record.kind}")


def client_from_env(
    env_file: str | Path | None = ".env",
    default_model: str = "gpt-4o-mini",
) -> ProviderClient:
    """
    Build a ProviderClient directly from environment variables and an optional
    env file.  Used by the CLI path where no DB-backed ProviderRecord exists.

    Raises RuntimeError if OPENAI_API_KEY is not set.
    """
    from reveng.framework.env import load_env_file

    file_values: dict[str, str] = {}
    if env_file is not None:
        file_values = load_env_file(env_file)

    api_key = os.environ.get(
        "OPENAI_API_KEY", file_values.get("OPENAI_API_KEY", "")
    ).strip()
    model = os.environ.get(
        "OPENAI_MODEL", file_values.get("OPENAI_MODEL", default_model)
    ).strip()
    base_url = os.environ.get(
        "OPENAI_BASE_URL",
        file_values.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    ).strip().rstrip("/")

    ollama_url = os.environ.get(
        "OLLAMA_BASE_URL", file_values.get("OLLAMA_BASE_URL", "")
    ).strip()

    if ollama_url:
        ollama_model = os.environ.get(
            "OLLAMA_MODEL", file_values.get("OLLAMA_MODEL", model)
        ).strip() or model
        return OllamaClient(
            provider_id="ollama",
            base_url=ollama_url,
            model=ollama_model,
        )

    if not api_key:
        env_path = Path(env_file).expanduser().resolve() if env_file is not None else None
        if env_path is not None:
            raise RuntimeError(
                f"OPENAI_API_KEY is not set in environment or env file: {env_path}"
            )
        raise RuntimeError("OPENAI_API_KEY is not set")

    return OpenAIClient(
        provider_id="openai",
        base_url=base_url,
        api_key=api_key,
        model=model,
    )
