from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    application = create_app(tmp_path / "data")
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture
def sample_kml() -> bytes:
    return b'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Placemark><name>sample polygon</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
    -122.0,37.0,0 -121.999,37.0,0 -121.999,37.001,0 -122.0,37.001,0 -122.0,37.0,0
  </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
  <Placemark><name>sample line</name><LineString><coordinates>-122.0,37.0,0 -121.999,37.0,0</coordinates></LineString></Placemark>
  <Placemark><name>sample point</name><Point><coordinates>-122.0,37.0,0</coordinates></Point></Placemark>
</Document></kml>'''