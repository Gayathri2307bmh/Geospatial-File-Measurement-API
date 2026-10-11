import io
import zipfile

import geopandas as gpd
from shapely.geometry import Point


def test_upload_then_get_metadata_and_measurements(client, sample_kml):
    uploaded = client.post(
        "/api/files/",
        files={"file": ("sample.kml", sample_kml, "application/vnd.google-earth.kml+xml")},
    )

    assert uploaded.status_code == 201, uploaded.text
    upload_body = uploaded.json()
    assert upload_body["feature_count"] == 3
    assert upload_body["original_crs"]
    assert upload_body["status"] == "completed"

    metadata = client.get(f"/api/files/{upload_body['file_id']}/")
    measurements = client.get(f"/api/files/{upload_body['file_id']}/measurements/")

    assert metadata.status_code == 200
    assert metadata.json()["filename"] == "sample.kml"
    assert measurements.status_code == 200
    features = measurements.json()["features"]
    by_type = {feature["geometry_type"]: feature for feature in features}
    assert by_type["Polygon"]["measurements"]["area_m2"] > 0
    assert by_type["LineString"]["measurements"]["length_m"] > 0
    assert by_type["Point"]["measurements"] == {}


def test_upload_zipped_shapefile(client, tmp_path):
    shapefile = tmp_path / "places.shp"
    frame = gpd.GeoDataFrame({"name": ["place"]}, geometry=[Point(-122, 37)], crs="EPSG:4326")
    frame.to_file(shapefile, driver="ESRI Shapefile", engine="pyogrio")
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        for sidecar in tmp_path.glob("places.*"):
            archive.write(sidecar, sidecar.name)

    response = client.post(
        "/api/files/",
        files={"file": ("places.zip", archive_buffer.getvalue(), "application/zip")},
    )

    assert response.status_code == 201, response.text
    assert response.json()["feature_count"] == 1
    assert response.json()["original_crs"]


def test_rejects_unsupported_extension(client):
    response = client.post("/api/files/", files={"file": ("notes.txt", b"text", "text/plain")})

    assert response.status_code == 415


def test_rejects_corrupt_kml_and_zip(client):
    bad_kml = client.post("/api/files/", files={"file": ("broken.kml", b"<not-kml", "application/xml")})
    bad_zip = client.post("/api/files/", files={"file": ("broken.zip", b"not a zip", "application/zip")})

    assert bad_kml.status_code == 422
    assert bad_zip.status_code == 422


def test_rejects_zip_without_required_shapefile_components(client):
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("roads.shp", b"not a complete shapefile")

    response = client.post(
        "/api/files/",
        files={"file": ("incomplete.zip", archive_buffer.getvalue(), "application/zip")},
    )

    assert response.status_code == 422
    assert ".shx" in response.json()["detail"]


def test_rejects_zip_path_traversal(client, tmp_path):
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("../escape.shp", b"shp")
        archive.writestr("../escape.shx", b"shx")
        archive.writestr("../escape.dbf", b"dbf")

    response = client.post(
        "/api/files/",
        files={"file": ("unsafe.zip", archive_buffer.getvalue(), "application/zip")},
    )

    assert response.status_code == 422
    assert "unsafe file path" in response.json()["detail"]
    assert not (tmp_path / "escape.shp").exists()


def test_missing_file_id_returns_404(client):
    assert client.get("/api/files/does-not-exist/").status_code == 404
    assert client.get("/api/files/does-not-exist/measurements/").status_code == 404