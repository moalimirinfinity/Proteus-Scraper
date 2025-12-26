from fastapi import FastAPI

from api.routes import router
from core.redis import close_redis


def create_app() -> FastAPI:
    app = FastAPI(title="Proteus-Scraper API")
    app.include_router(router)

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        await close_redis()

    return app


app = create_app()
