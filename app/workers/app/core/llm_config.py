"""
Configuration LLM — Support Ollama (local) + vLLM + fallback OpenAI.
Priorité : local d'abord (coût zéro, souveraineté données CI).
"""
from __future__ import annotations

from pydantic_settings import BaseSettings


class LLMSettings(BaseSettings):
    # ─── Provider principal ─────────────────────────────────
    LLM_PROVIDER: str = "ollama"          # ollama | vllm | openai

    # ─── Ollama (local, recommandé) ─────────────────────────
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "llama3.1:8b-instruct-q5_K_M"
    OLLAMA_MODEL_FAST: str = "llama3.2:3b-instruct-q5_K_M"
    OLLAMA_TIMEOUT: int = 120
    OLLAMA_NUM_CTX: int = 8192
    OLLAMA_NUM_PREDICT: int = 1024
    OLLAMA_TEMPERATURE: float = 0.1

    # ─── vLLM (GPU, haute perf) ─────────────────────────────
    VLLM_BASE_URL: str = "http://vllm:8000/v1"
    VLLM_MODEL: str = "Qwen/Qwen2.5-7B-Instruct"
    VLLM_API_KEY: str = ""

    # ─── OpenAI (fallback cloud) ────────────────────────────
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    # ─── Embeddings ─────────────────────────────────────────
    EMBEDDING_PROVIDER: str = "ollama"     # ollama | openai
    EMBEDDING_MODEL: str = "nomic-embed-text"
    EMBEDDING_DIMENSION: int = 768          # nomic-embed-text = 768

    # ─── Streaming ──────────────────────────────────────────
    STREAM_CHUNK_SIZE: int = 20             # tokens par chunk SSE
    STREAM_TIMEOUT_S: int = 300

    model_config = {"env_file": ".env", "extra": "ignore"}


llm_settings = LLMSettings()
