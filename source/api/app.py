from __future__ import annotations

from fastapi import FastAPI

from api.ats_domain_routes import router as ats_domain_router
from api.routes import router as api_router
from utils.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Job Scraper API", version="0.1.0")
    app.include_router(ats_domain_router, prefix="/api")
    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
