"""
Registre d'outils — outils disponibles pour le LLM.
Format compatible Ollama/OpenAI (JSON Schema).
"""
from __future__ import annotations

from typing import Any, Callable, Awaitable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


class Tool:
    """Définition d'un outil."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[..., Awaitable[dict[str, Any]]],
        require_admin: bool = False,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.require_admin = require_admin

    def to_llm_schema(self) -> dict[str, Any]:
        """Format JSON Schema pour le LLM."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registre central des outils disponibles."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_schemas(self, role: str | None = None) -> list[dict[str, Any]]:
        """Retourne les schémas des outils disponibles pour un rôle."""
        result = []
        for tool in self._tools.values():
            if tool.require_admin and role not in ("ADMIN_TENANT", "SUPER_ADMIN"):
                continue
            result.append(tool.to_llm_schema())
        return result

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        db: AsyncSession,
        tenant_id: UUID,
        user_id: UUID,
        role: str,
    ) -> dict[str, Any]:
        """Exécute un outil avec les arguments fournis par le LLM."""
        tool = self.get(name)
        if tool is None:
            return {"error": f"Outil inconnu : {name}"}

        if tool.require_admin and role not in ("ADMIN_TENANT", "SUPER_ADMIN"):
            return {"error": f"Permission refusée pour l'outil {name}"}

        try:
            return await tool.handler(
                db=db,
                tenant_id=tenant_id,
                user_id=user_id,
                **arguments,
            )
        except Exception as exc:
            return {"error": str(exc)}


tool_registry = ToolRegistry()
