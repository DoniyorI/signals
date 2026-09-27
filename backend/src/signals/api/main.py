"""FastAPI application factory. Every router lives under /api."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from signals.api.routers import (
    companies,
    compare,
    feed,
    funds,
    health,
    insiders,
    jobs,
    screener,
    search,
    watchlists,
)

ROUTERS = (feed, insiders, companies, funds, screener, compare, search, watchlists, health, jobs)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Signals: SEC insider dashboard API",
        version="0.1.0",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )
    for module in ROUTERS:
        app.include_router(module.router, prefix="/api")

    @app.exception_handler(NotImplementedError)
    async def _not_implemented(request: Request, exc: NotImplementedError) -> JSONResponse:
        return JSONResponse(status_code=501, content={"detail": "not implemented"})

    return app


app = create_app()
