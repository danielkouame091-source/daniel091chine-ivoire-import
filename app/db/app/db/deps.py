from typing import AsyncGenerator
from sqlalchemy import text
from fastapi import Depends, Request
from app.db.session import AsyncSessionLocal

async def get_db() -> AsyncGenerator:
    async with AsyncSessionLocal() as session:
        yield session

async def get_tenant_db(request: Request) -> AsyncGenerator:
    """
    Session avec RLS activé : set_config app.tenant_id + app.read_only.
    ⚠️ set_config(..., true) = LOCAL à la transaction.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    read_only = "true" if getattr(request.state, "read_only", False) else "false"

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tid, true), "
                     "       set_config('app.read_only', :ro, true)"),
                {"tid": str(tenant_id) if tenant_id else None, "ro": read_only},
            )
            yield session
