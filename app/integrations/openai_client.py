"""
Client OpenAI robuste : retry exponentiel, timeout, comptage tokens,
mode JSON strict, fallback modèle premium.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from openai import APIConnectionError, APIError, AsyncOpenAI, RateLimitError

from app.core.config import settings

logger = logging.getLogger(__name__)


class OpenAIClient:
    """
    Wrapper unique pour tous les appels OpenAI.
    ⚠️ Ne jamais instancier AsyncOpenAI ailleurs dans le code.
    """

    def __init__(self) -> None:
        if not settings.nlp_enabled:
            raise RuntimeError(
                "OPENAI_API_KEY absente — le client OpenAI ne peut pas être instancié."
            )
        self._client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=settings.OPENAI_TIMEOUT,
            max_retries=0,   # on gère le retry nous-mêmes
        )

    async def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """
        Appel chat completion en mode JSON strict.
        Retourne : {"content": dict, "tokens_prompt": int, "tokens_completion": int, "latence_ms": int, "model": str}
        """
        model = model or settings.OPENAI_MODEL
        temperature = temperature if temperature is not None else settings.NLP_TEMPERATURE
        max_tokens = max_tokens or settings.NLP_MAX_TOKENS

        last_error: Exception | None = None
        for attempt in range(settings.OPENAI_MAX_RETRIES):
            started = time.monotonic()
            try:
                response = await self._client.chat.completions.create(
                    model=model,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                latence_ms = int((time.monotonic() - started) * 1000)

                content_raw = response.choices[0].message.content or "{}"
                import json
                content = json.loads(content_raw)

                return {
                    "content": content,
                    "tokens_prompt": response.usage.prompt_tokens if response.usage else None,
                    "tokens_completion": response.usage.completion_tokens if response.usage else None,
                    "latence_ms": latence_ms,
                    "model": model,
                }

            except (RateLimitError, APIConnectionError) as exc:
                last_error = exc
                wait = 2 ** attempt
                logger.warning(f"[openai] Tentative {attempt + 1} échouée ({exc.__class__.__name__}), retry dans {wait}s")
                await asyncio.sleep(wait)
            except APIError as exc:
                last_error = exc
                # Erreur non-retryable (ex: prompt trop long) → fallback premium
                if "context_length" in str(exc).lower() and model != settings.OPENAI_MODEL_PREMIUM:
                    logger.warning("[openai] Contexte trop long, bascule sur modèle premium")
                    return await self.chat_json(
                        system_prompt, user_prompt,
                        model=settings.OPENAI_MODEL_PREMIUM,
                        temperature=temperature, max_tokens=max_tokens,
                    )
                raise

        raise RuntimeError(f"OpenAI échoué après {settings.OPENAI_MAX_RETRIES} tentatives : {last_error}")

    async def chat_text(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 800,
    ) -> str:
        """Appel chat completion classique (réponse texte libre)."""
        model = model or settings.OPENAI_MODEL
        response = await self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""


# Singleton
_client: OpenAIClient | None = None


def get_openai_client() -> OpenAIClient:
    global _client
    if _client is None:
        _client = OpenAIClient()
    return _client
