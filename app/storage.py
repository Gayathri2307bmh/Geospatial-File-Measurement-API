import json
import sqlite3
from pathlib import Path
from typing import Any


class FileStorage:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.upload_dir = data_dir / "uploads"
        self.database_path = data_dir / "measurements.sqlite3"

    def initialize(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    feature_count INTEGER NOT NULL,
                    original_crs TEXT,
                    measurement_crs TEXT,
                    status TEXT NOT NULL,
                    warnings TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    features TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def save_file(self, record: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO files (
                    id, filename, feature_count, original_crs, measurement_crs,
                    status, warnings, created_at, features
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["file_id"],
                    record["filename"],
                    record["feature_count"],
                    record["original_crs"],
                    record["measurement_crs"],
                    record["status"],
                    json.dumps(record["warnings"], allow_nan=False),
                    record["created_at"],
                    json.dumps(record["features"], allow_nan=False),
                ),
            )

    def get_file(self, file_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM files WHERE id = ?", (file_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "file_id": row["id"],
            "filename": row["filename"],
            "feature_count": row["feature_count"],
            "original_crs": row["original_crs"],
            "measurement_crs": row["measurement_crs"],
            "status": row["status"],
            "warnings": json.loads(row["warnings"]),
            "created_at": row["created_at"],
            "features": json.loads(row["features"]),
        }