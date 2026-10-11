import logging
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import geopandas as gpd

from app.measurements import measure_features

logger = logging.getLogger(__name__)
MAX_ARCHIVE_FILES = 100
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024


class InvalidGeospatialFile(Exception):
    """Raised when an upload is not a supported, readable geospatial file."""


def _validate_kml(path: Path) -> None:
    try:
        with path.open("rb") as source:
            prefix = source.read(1024 * 1024).upper()
        if b"<!DOCTYPE" in prefix or b"<!ENTITY" in prefix:
            raise InvalidGeospatialFile("KML document types and entities are not supported.")
        root = ET.parse(path).getroot()
        if root.tag.rsplit("}", 1)[-1].lower() != "kml":
            raise InvalidGeospatialFile("Uploaded XML is not a KML document.")
    except InvalidGeospatialFile:
        raise
    except (ET.ParseError, OSError) as exc:
        raise InvalidGeospatialFile("KML content is malformed or unreadable.") from exc


def _safe_zip_members(archive: zipfile.ZipFile) -> tuple[list[zipfile.ZipInfo], str]:
    members = [item for item in archive.infolist() if not item.is_dir()]
    if len(members) > MAX_ARCHIVE_FILES:
        raise InvalidGeospatialFile("ZIP contains too many files.")
    if not members:
        raise InvalidGeospatialFile("ZIP archive is empty.")

    names: set[str] = set()
    basenames: dict[str, str] = {}
    total_size = 0
    for member in members:
        normalized = member.filename.replace("\\", "/")
        posix = PurePosixPath(normalized)
        windows = PureWindowsPath(member.filename)
        if (
            posix.is_absolute()
            or windows.is_absolute()
            or windows.drive
            or ".." in posix.parts
            or ".." in windows.parts
        ):
            raise InvalidGeospatialFile("ZIP contains an unsafe file path.")
        if member.flag_bits & 0x1:
            raise InvalidGeospatialFile("Encrypted ZIP entries are not supported.")
        mode = member.external_attr >> 16
        if mode and (mode & 0o170000) == 0o120000:
            raise InvalidGeospatialFile("ZIP symbolic links are not supported.")
        basename = posix.name
        if not basename:
            raise InvalidGeospatialFile("ZIP contains an invalid file name.")
        folded = basename.casefold()
        if folded in basenames:
            raise InvalidGeospatialFile("ZIP contains duplicate file names.")
        basenames[folded] = basename
        names.add(folded)
        total_size += member.file_size
        if total_size > MAX_UNCOMPRESSED_BYTES:
            raise InvalidGeospatialFile("ZIP expands beyond the allowed size.")

    shapefiles = [name for name in names if name.endswith(".shp")]
    if len(shapefiles) != 1:
        raise InvalidGeospatialFile("ZIP must contain exactly one Shapefile (.shp).")
    stem = shapefiles[0][:-4]
    missing = [suffix for suffix in (".shx", ".dbf") if f"{stem}{suffix}" not in names]
    if missing:
        raise InvalidGeospatialFile(
            "Shapefile is missing required component(s): " + ", ".join(missing)
        )
    return members, basenames[shapefiles[0]]


def _read_shapefile_zip(path: Path) -> gpd.GeoDataFrame:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise InvalidGeospatialFile("Uploaded ZIP archive is corrupt or unreadable.") from exc

    with archive:
        members, shapefile_name = _safe_zip_members(archive)
        with tempfile.TemporaryDirectory(prefix="geospatial-upload-") as directory:
            target_dir = Path(directory)
            total_written = 0
            try:
                for member in members:
                    destination = target_dir / PurePosixPath(member.filename.replace("\\", "/")).name
                    written = 0
                    with archive.open(member) as source, destination.open("wb") as output:
                        while chunk := source.read(1024 * 1024):
                            written += len(chunk)
                            total_written += len(chunk)
                            if total_written > MAX_UNCOMPRESSED_BYTES or written > member.file_size:
                                raise InvalidGeospatialFile("ZIP expands beyond the allowed size.")
                            output.write(chunk)
                    if written != member.file_size:
                        raise InvalidGeospatialFile("ZIP entry size does not match its contents.")
                gdf = gpd.read_file(target_dir / shapefile_name, engine="pyogrio")
            except InvalidGeospatialFile:
                raise
            except Exception as exc:
                logger.info("Unable to read Shapefile archive: %s", exc)
                raise InvalidGeospatialFile("ZIP does not contain a readable Shapefile.") from exc
    return gdf


def process_geospatial_file(path: Path, suffix: str) -> dict[str, Any]:
    if suffix == ".kml":
        _validate_kml(path)
        try:
            gdf = gpd.read_file(path, engine="pyogrio")
        except Exception as exc:
            logger.info("Unable to read KML upload: %s", exc)
            raise InvalidGeospatialFile("KML document could not be read as geospatial data.") from exc
    elif suffix == ".zip":
        gdf = _read_shapefile_zip(path)
    else:
        raise InvalidGeospatialFile("Only .kml and .zip uploads are supported.")

    if gdf.empty:
        raise InvalidGeospatialFile("Geospatial dataset contains no features.")
    features, measurement_crs, warnings = measure_features(gdf)
    if any(feature.get("measurement_note") for feature in features):
        status = "completed_with_warnings"
    else:
        status = "completed"
    return {
        "feature_count": len(features),
        "original_crs": gdf.crs.to_string() if gdf.crs is not None else None,
        "measurement_crs": measurement_crs,
        "features": features,
        "warnings": warnings,
        "status": status,
    }