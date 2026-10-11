import geopandas as gpd
from shapely.geometry import GeometryCollection, LineString, Point, Polygon

from app.measurements import measure_features


def test_measures_polygon_and_line_in_projected_metres_and_preserves_point():
    frame = gpd.GeoDataFrame(
        {"label": ["parcel", "road", "marker"]},
        geometry=[
            Polygon([(-122, 37), (-121.999, 37), (-121.999, 37.001), (-122, 37.001)]),
            LineString([(-122, 37), (-121.999, 37)]),
            Point(-122, 37),
        ],
        crs="EPSG:4326",
    )

    features, measurement_crs, warnings = measure_features(frame)

    assert measurement_crs is not None
    assert "326" in measurement_crs or "327" in measurement_crs
    assert features[0]["measurements"]["area_m2"] > 0
    assert features[1]["measurements"]["length_m"] > 0
    assert features[2]["measurements"] == {}
    assert features[2]["geometry_type"] == "Point"
    assert features[0]["crs"] == "EPSG:4326"
    assert features[0]["properties"]["label"] == "parcel"
    assert warnings == []


def test_missing_crs_does_not_calculate_planar_measurements():
    frame = gpd.GeoDataFrame(
        {"label": ["parcel"]},
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
    )

    features, measurement_crs, warnings = measure_features(frame)

    assert measurement_crs is None
    assert features[0]["measurements"] == {}
    assert "CRS is missing" in features[0]["measurement_note"]
    assert warnings


def test_unsupported_geometry_is_serialized_without_crashing():
    frame = gpd.GeoDataFrame(
        {"label": ["collection"]},
        geometry=[GeometryCollection([Point(1, 2)])],
        crs="EPSG:4326",
    )

    features, _, warnings = measure_features(frame)

    assert features[0]["geometry_type"] == "GeometryCollection"
    assert features[0]["geometry"]["type"] == "GeometryCollection"
    assert features[0]["measurements"] == {}
    assert features[0]["measurement_note"]
    assert warnings