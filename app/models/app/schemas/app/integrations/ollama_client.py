"""
Client Ollama — LLM local + embeddings.
Support streaming (SSE).
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from app.core.llm_config import llm_settings

logger = logging.getLogger(__name__)


class OllamaClient:
    """Client HTTP pour Ollama."""

    def __init__(self) -> None:
        self.base_url = llm_settings.OLLAMA_BASE_URL.rstrip("/")
        self.timeout = httpx.Timeout(llm_settings.OLLAMA_TIMEOUT)

    # ═════════════════════════════════════════════════════════════════════
    # CHAT COMPLETION
    # ═════════════════════════════════════════════════════════════════════
    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        format_json: bool = False,
    ) -> dict[str, Any]:
        """Appel chat completion (non-streaming)."""
        payload: dict[str, Any] = {
            "model": model or llm_settings.OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature if temperature is not None else llm_settings.OLLAMA_TEMPERATURE,
                "num_ctx": llm_settings.OLLAMA_NUM_CTX,
                "num_predict": llm_settings.OLLAMA_NUM_PREDICT,
            },
        }
        if tools:
            payload["tools"] = tools
        if format_json:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(f"{self.base_url}/api/chat", json=payload)
            r.raise_for_status()
            return r.json()

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Appel chat completion en streaming — yield des chunks JSON."""
        payload: dict[str, Any] = {
            "model": model or llm_settings.OLLAMA_MODEL,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature if temperature is not None else llm_settings.OLLAMA_TEMPERATURE,
                "num_ctx": llm_settings.OLLAMA_NUM_CTX,
                "num_predict": llm_settings.OLLAMA_NUM_PREDICT,
            },
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue

    # ═════════════════════════════════════════════════════════════════════
    # EMBEDDINGS
    # ═════════════════════════════════════════════════════════════════════
    async def embed(self, text: str) -> list[float]:
        """Génère un embedding pour un texte."""
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": llm_settings.EMBEDDING_MODEL, "prompt": text},
            )
            r.raise_for_status()
            return r.json()["embedding"]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Génère des embeddings en batch (parallèle)."""
        import asyncio
        return await asyncio.gather(*[self.embed(t) for t in texts])

    # ═════════════════════════════════════════════════════════════════════
    # HEALTH
    # ═════════════════════════════════════════════════════════════════════
    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{self.base_url}/api/tags")
                return r.status_code == 200
        except Exception:
            return False


ollama_client = OllamaClient()
