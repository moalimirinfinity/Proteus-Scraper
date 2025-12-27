from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from api.routes import router
from core.config import settings
from core.redis import close_redis


def create_app() -> FastAPI:
    app = FastAPI(title="Proteus-Scraper API")
    app.include_router(router)

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        await close_redis()

    @app.get("/metrics")
    async def metrics() -> Response:
        if not settings.metrics_enabled:
            return Response(status_code=404)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
