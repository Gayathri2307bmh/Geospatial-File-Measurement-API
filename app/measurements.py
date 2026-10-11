import logging
import math
from datetime import date, datetime
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import CRS, Transformer
from shapely.geometry import mapping
from shapely import transform

logger = logging.getLogger(__name__)

POLYGON_TYPES = {"Polygon", "MultiPolygon"}
LINE_TYPES = {"LineString", "MultiLineString"}


def to_json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return to_json_safe(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    try:
        missing = pd.isna(value)
        if isinstance(missing, (bool, np.bool_)) and missing:
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _metric_crs(gdf: gpd.GeoDataFrame) -> tuple[CRS | None, str | None]:
    if gdf.crs is None:
        return None, "Source CRS is missing; measurements were not calculated."

    try:
        source_crs = CRS.from_user_input(gdf.crs)
        geographic = gdf.to_crs("EPSG:4326")
        bounds = geographic.total_bounds
    except Exception as exc:
        logger.info("Unable to resolve a usable source CRS: %s", exc)
        return None, "Source CRS is invalid or could not be transformed; measurements were not calculated."

    if not all(math.isfinite(float(value)) for value in bounds):
        return None, "Dataset bounds are invalid; measurements were not calculated."

    west, south, east, north = (float(value) for value in bounds)
    if (
        west < -180
        or east > 180
        or south < -80
        or north > 84
        or east - west > 6.5
        or north - south > 8
    ):
        return None, "Dataset is outside a suitable local UTM area; measurements were not calculated."

    try:
        estimated = geographic.estimate_utm_crs()
        if estimated is None:
            return None, "A suitable local projected CRS could not be estimated; measurements were not calculated."
        target = CRS.from_user_input(estimated)
        if not target.is_projected:
            return None, "A projected measurement CRS could not be selected; measurements were not calculated."
        return target, None
    except Exception as exc:
        logger.info("Unable to estimate a local UTM CRS: %s", exc)
        return None, "A suitable local projected CRS could not be estimated; measurements were not calculated."


def measure_features(
    gdf: gpd.GeoDataFrame,
) -> tuple[list[dict[str, Any]], str | None, list[str]]:
    try:
        source_crs = CRS.from_user_input(gdf.crs).to_string() if gdf.crs is not None else None
    except Exception:
        source_crs = None
    metric_crs, crs_warning = _metric_crs(gdf)
    warnings: list[str] = [crs_warning] if crs_warning else []
    transformer = None
    if metric_crs is not None:
        transformer = Transformer.from_crs(CRS.from_user_input(gdf.crs), metric_crs, always_xy=True)

    features: list[dict[str, Any]] = []
    for index, row in gdf.iterrows():
        geometry = row.geometry
        geometry_type = geometry.geom_type if geometry is not None else "None"
        measurements: dict[str, float] = {}
        measurement_note: str | None = None

        if geometry is None or geometry.is_empty:
            measurement_note = "Geometry is empty; measurements were not calculated."
            warnings.append(measurement_note)
        elif geometry_type in POLYGON_TYPES | LINE_TYPES:
            if transformer is None:
                measurement_note = crs_warning
            elif not geometry.is_valid:
                measurement_note = "Geometry is invalid; measurements were not calculated."
                warnings.append(measurement_note)
            else:
                projected = transform(geometry, transformer.transform, interleaved=False)
                if geometry_type in POLYGON_TYPES:
                    measurements["area_m2"] = float(projected.area)
                else:
                    measurements["length_m"] = float(projected.length)
        elif geometry_type != "Point" and geometry_type != "MultiPoint":
            measurement_note = f"Measurements are not defined for {geometry_type} geometry."
            warnings.append(measurement_note)

        try:
            serialized_geometry = to_json_safe(mapping(geometry)) if geometry is not None else None
        except Exception:
            serialized_geometry = None
            measurement_note = "Geometry could not be serialized."
            warnings.append(measurement_note)

        properties = {
            str(column): to_json_safe(row[column])
            for column in gdf.columns
            if column != gdf.geometry.name
        }
        feature: dict[str, Any] = {
            "feature_id": to_json_safe(index),
            "geometry_type": geometry_type,
            "geometry": serialized_geometry,
            "crs": source_crs,
            "properties": properties,
            "measurements": measurements,
        }
        if measurement_note:
            feature["measurement_note"] = measurement_note
        features.append(feature)

    return features, metric_crs.to_string() if metric_crs else None, list(dict.fromkeys(warnings))