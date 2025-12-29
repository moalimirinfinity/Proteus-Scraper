from pathlib import Path

from fastapi import FastAPI, Response

BASE_DIR = Path(__file__).resolve().parents[1]
HTML_DIR = BASE_DIR / "fixtures" / "html"

app = FastAPI()


def _load_html(name: str) -> str:
    return (HTML_DIR / name).read_text(encoding="utf-8")


@app.get("/product")
async def product() -> Response:
    return Response(_load_html("product.html"), media_type="text/html")


@app.get("/list")
async def list_page() -> Response:
    return Response(_load_html("list.html"), media_type="text/html")


@app.get("/blocked")
async def blocked() -> Response:
    return Response(
        _load_html("blocked.html"),
        media_type="text/html",
        status_code=403,
        headers={"X-Blocked": "1"},
    )


@app.get("/broken")
async def broken() -> Response:
    return Response(_load_html("broken.html"), media_type="text/html")
