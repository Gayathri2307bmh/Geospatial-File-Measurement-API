import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

from app.routes import router
from app.storage import FileStorage


def create_app(data_dir: Path | None = None) -> FastAPI:
    configured_dir = data_dir or Path(os.getenv("GEOSPATIAL_DATA_DIR", "data"))
    storage = FileStorage(configured_dir)
    storage.initialize()

    application = FastAPI(
        title="Geospatial File Measurement API",
        description="Upload KML and zipped Shapefile data and retrieve CRS-aware measurements.",
        version="1.0.0",
    )
    application.state.file_storage = storage
    application.include_router(router)

    @application.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = create_app()