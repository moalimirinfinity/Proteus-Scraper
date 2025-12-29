from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from api.auth import AuthError, auth_required, authenticate_request, csrf_valid
from api.routes import router
from core.config import settings
from core.redis import close_redis
from scraper.fetcher import close_http_clients


def create_app() -> FastAPI:
    app = FastAPI(title="Proteus-Scraper API")
    app.include_router(router)
    app.mount("/ui", StaticFiles(directory="web", html=True), name="ui")

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        if request.url.path.startswith("/ui"):
            return await call_next(request)
        if not auth_required():
            return await call_next(request)
        if request.url.path == "/metrics" and not settings.auth_protect_metrics:
            return await call_next(request)
        try:
            auth_ctx = authenticate_request(request)
            request.state.auth = auth_ctx
        except AuthError as exc:
            return JSONResponse(
                status_code=401,
                content={"detail": exc.code},
            )
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and auth_ctx.source == "cookie":
            if not csrf_valid(request):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "csrf_failed"},
                )
        return await call_next(request)

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        await close_redis()
        await close_http_clients()

    @app.get("/metrics")
    async def metrics() -> Response:
        if not settings.metrics_enabled:
            return Response(status_code=404)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
