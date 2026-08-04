from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.services.local_owner_service import LocalOwnerService


async def provision_local_owner() -> None:
    """Ensure the local V1 owner exists after the database schema is migrated."""

    from app.db.session import SessionLocal
    from app.repositories.user_repository import UserRepository

    with SessionLocal() as session:
        LocalOwnerService(UserRepository(session)).ensure_owner()
        session.commit()


def create_app(*, provision_owner_on_startup: bool = True) -> FastAPI:
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if provision_owner_on_startup:
            await provision_local_owner()
        yield

    app = FastAPI(title="Gmail Manager API", version="0.2.0", lifespan=lifespan)

    @app.get("/health", tags=["system"])
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
