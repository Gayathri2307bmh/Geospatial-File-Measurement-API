import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status

from app.processor import InvalidGeospatialFile, process_geospatial_file
from app.storage import FileStorage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/files", tags=["files"])
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


async def _save_upload(upload: UploadFile, destination: Path) -> None:
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := await upload.read(CHUNK_SIZE):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Upload exceeds the 50 MiB limit.",
                    )
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def _storage(request: Request) -> FileStorage:
    return request.app.state.file_storage


@router.post("/", status_code=status.HTTP_201_CREATED)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    submitted_name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not submitted_name or submitted_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="A valid filename is required.")
    suffix = Path(submitted_name).suffix.lower()
    if suffix not in {".kml", ".zip"}:
        raise HTTPException(status_code=415, detail="Only .kml and .zip files are supported.")

    storage = _storage(request)
    file_id = str(uuid.uuid4())
    upload_path = storage.upload_dir / f"{file_id}{suffix}"
    try:
        await _save_upload(file, upload_path)
        processed = process_geospatial_file(upload_path, suffix)
        record = {
            "file_id": file_id,
            "filename": submitted_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **processed,
        }
        storage.save_file(record)
    except HTTPException:
        upload_path.unlink(missing_ok=True)
        raise
    except InvalidGeospatialFile as exc:
        upload_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        upload_path.unlink(missing_ok=True)
        logger.exception("Unexpected error processing upload %s", file_id)
        raise HTTPException(status_code=500, detail="Unable to process uploaded file.") from exc

    return {
        "file_id": file_id,
        "filename": record["filename"],
        "feature_count": record["feature_count"],
        "original_crs": record["original_crs"],
        "status": record["status"],
        "warnings": record["warnings"],
    }


@router.get("/{file_id}/")
def get_file_metadata(request: Request, file_id: str) -> dict[str, Any]:
    record = _storage(request).get_file(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File ID was not found.")
    return {key: value for key, value in record.items() if key not in {"features", "measurement_crs"}}


@router.get("/{file_id}/measurements/")
def get_file_measurements(request: Request, file_id: str) -> dict[str, Any]:
    record = _storage(request).get_file(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File ID was not found.")
    return {
        "file_id": record["file_id"],
        "filename": record["filename"],
        "feature_count": record["feature_count"],
        "original_crs": record["original_crs"],
        "measurement_crs": record["measurement_crs"],
        "status": record["status"],
        "warnings": record["warnings"],
        "features": record["features"],
    }