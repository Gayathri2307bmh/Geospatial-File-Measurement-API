# Geospatial File Measurement API

A local FastAPI backend that accepts KML and zipped Shapefile uploads, extracts feature geometry and attributes, and calculates polygon area or line length in metres. Processed feature responses and metadata are persisted in SQLite so they remain available across separate HTTP requests and application restarts.

## Prerequisites

- Windows 10/11, macOS, or Linux
- Python 3.10 or newer (64-bit recommended for the geospatial wheels)
- `pip` and internet access for installing packages

The project uses Pyogrio/GDAL through GeoPandas to read KML and Shapefile formats. Pyogrio provides prebuilt wheels for common platforms and avoids requiring a local GDAL compilation toolchain. The optional `.env` file is loaded at startup.

## Setup and run on Windows

Open PowerShell in the project directory:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again. The app is available at `http://127.0.0.1:8000`; interactive Swagger documentation is at `http://127.0.0.1:8000/docs`. The database and originals are created in `data/` by default. Set `GEOSPATIAL_DATA_DIR` to use another directory.

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

## API endpoints

All endpoints return JSON. Uploads are limited to 50 MiB; ZIP contents are limited to 100 MiB uncompressed and 100 entries.

### `POST /api/files/`

Multipart form field: `file`. Supported filename extensions are `.kml` and `.zip`; content is also validated. A successful response uses HTTP 201:

```json
{
  "file_id": "b87eae6a-92c4-4f90-a62e-02e9347b87a4",
  "filename": "sample.kml",
  "feature_count": 2,
  "original_crs": "EPSG:4326",
  "status": "completed",
  "warnings": []
}
```

Example with curl:

```bash
curl -F "file=@sample.kml" http://127.0.0.1:8000/api/files/
curl -F "file=@roads.zip" http://127.0.0.1:8000/api/files/
```

PowerShell equivalent:

```powershell
curl.exe -F "file=@sample.kml" http://127.0.0.1:8000/api/files/
```

### `GET /api/files/{id}/`

Returns stored metadata: `file_id`, `filename`, `feature_count`, `original_crs`, `status`, `warnings`, and `created_at`.

```bash
curl http://127.0.0.1:8000/api/files/b87eae6a-92c4-4f90-a62e-02e9347b87a4/
```

### `GET /api/files/{id}/measurements/`

Returns the source and measurement CRS plus a `features` array. Every feature contains `feature_id`, `geometry_type`, GeoJSON-like `geometry` coordinates, source `crs`, `properties`, and `measurements`. Polygon and MultiPolygon features have `area_m2`; LineString and MultiLineString features have `length_m`; points return an empty measurements object. Unsupported geometry types remain in the response with a `measurement_note`.

```bash
curl http://127.0.0.1:8000/api/files/b87eae6a-92c4-4f90-a62e-02e9347b87a4/measurements/
```

A feature response looks like this (coordinates abbreviated):

```json
{
  "file_id": "b87eae6a-92c4-4f90-a62e-02e9347b87a4",
  "filename": "sample.kml",
  "feature_count": 1,
  "original_crs": "EPSG:4326",
  "measurement_crs": "EPSG:32610",
  "status": "completed",
  "warnings": [],
  "features": [
    {
      "feature_id": 0,
      "geometry_type": "Polygon",
      "geometry": {"type": "Polygon", "coordinates": "..."},
      "crs": "EPSG:4326",
      "properties": {"name": "parcel"},
      "measurements": {"area_m2": 9876.5}
    }
  ]
}
```

Replace the abbreviated coordinates with the full coordinate arrays in actual responses. Unknown IDs return HTTP 404, unsupported extensions return 415, invalid/corrupt content returns 422, and oversized uploads return 413. Errors use FastAPI's `{"detail": "..."}` structure; internal paths and stack traces are not returned.

## Try it in Swagger

1. Start the app with `uvicorn app.main:app --reload`.
2. Open `http://127.0.0.1:8000/docs` in a browser.
3. Expand `POST /api/files/`, click **Try it out**, choose a `.kml` or zipped Shapefile, and execute it.
4. Copy `file_id` from the response.
5. Enter that ID in `GET /api/files/{file_id}/` and execute; repeat with `GET /api/files/{file_id}/measurements/`.

## Architecture and processing flow

- `app/main.py` creates the app, initializes persistent storage, and registers routes.
- `app/routes.py` validates the filename and extension, streams the request into a UUID-named upload, invokes processing, and exposes the three API operations.
- `app/processor.py` validates KML XML and ZIP members, reads geospatial data with GeoPandas/Pyogrio, and turns invalid or empty datasets into client errors.
- `app/measurements.py` serializes each feature and chooses a local projected CRS before computing measurements.
- `app/storage.py` creates and accesses the SQLite table. JSON feature results make subsequent GET requests independent of parser state.
- `tests/` covers the API flow, both upload formats, malformed inputs, missing IDs, geometry measurements, and missing CRS behavior.

Upload processing is: check extension and size, save under a generated UUID (never the client path), inspect KML XML or ZIP structure, safely extract ZIP members into a temporary directory, read the dataset, serialize feature data and calculate measurements, then commit metadata and results to SQLite. Failed uploads are removed. Original successful uploads remain in `data/uploads/`.

## Measurement and CRS decisions

Measurements are never calculated directly in geographic degrees. The source CRS is retained in the response, transformed to EPSG:4326 to assess extent, and a local UTM CRS is estimated for datasets in a bounded UTM region (longitude width at most 6.5 degrees and latitude span at most 8 degrees, between 80 degrees south and 84 degrees north). Geometries are transformed with PyProj's `always_xy` axis order and Shapely before computing area or length, yielding square metres and metres.

Missing CRS is not guessed: geometry and attributes are returned, but metrics are omitted with a warning and `measurement_crs: null`. Invalid CRS, invalid geometry, or datasets too broad or too far outside UTM coverage likewise do not receive misleading metrics. An absent Shapefile `.prj` normally means no CRS; provide that sidecar when known. ZIP `.shp`, `.shx`, and `.dbf` files are required; `.prj` is optional. KML's conventional WGS 84 coordinates are interpreted by the KML driver.

## Tests

Install dependencies, activate the virtual environment, then run:

```powershell
python -m pytest -q
```

The tests use temporary directories and do not write test records into the normal `data/` folder.

## Design decisions and limitations

- SQLite and local disk keep the assignment self-contained and persistent without a separate database service.
- UUID names and basename-only client filenames prevent user input from controlling storage paths. ZIP traversal, symlinks, duplicate flattened names, encrypted entries, excessive member counts, and excessive expanded size are rejected.
- Measurements use one estimated UTM zone per dataset. This is appropriate for local datasets, not global data, very wide extents, or precision surveying. Those inputs are returned without metrics rather than silently approximated.
- There is no authentication, retention/cleanup policy, cloud object storage, background job queue, or multi-worker coordination for SQLite writes. Add these before exposing the service publicly.
- Large coordinate payloads are stored as JSON in SQLite; production-scale datasets should use object storage and paginated or asynchronous result retrieval.

## Learning outcomes

This project demonstrates multipart upload handling, content validation, safe archive processing, FastAPI routing, SQLite persistence, geospatial parsing, coordinate transformations, GeoJSON-style serialization, error handling, and pytest API tests.

## Future scope

Potential improvements include authentication and quotas, upload retention controls, configurable measurement projections, geodesic fallback for non-UTM areas, pagination, asynchronous processing, spatial database storage, and deployment/container automation.

## Public GitHub submission checklist

Review the repository before publishing. The `.gitignore` excludes `.env`, virtual environments, local SQLite files, and `data/`; verify that no private geospatial uploads, credentials, or personal data are staged. Confirm tests pass and the README reflects the behavior you intend to submit.

From PowerShell in this project directory, initialize and push to a public repository you create on GitHub (leave it empty when creating it):

```powershell
git init
git add .
git status
git commit -m "Build geospatial file measurement API"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/geospatial-file-measurement-api.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your account name and the remote URL with the actual public repository URL. Check the GitHub repository visibility is **Public**, then verify the README, source files, requirements, and tests appear online and that ignored data/secrets do not.