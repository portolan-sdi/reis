"""End-to-end data pass over a catalog with real asset bytes.

Builds a conformant Portolan catalog whose assets are genuine GeoParquet, COG,
and plain-GeoTIFF files, with checksums and sizes computed from the bytes at
build time — so nothing is committed and nothing can drift. The pristine catalog
passes the data pass cleanly; each test then mutates one field and asserts the
one finding it should raise.

Needs the ``reis[data]`` extra; skips without it. Fully local — no network.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("pyarrow")
pytest.importorskip("rasterio")
pytest.importorskip("rio_cogeo")

import numpy as np  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
import rasterio  # noqa: E402
from pyproj import CRS  # noqa: E402
from rasterio.transform import from_bounds  # noqa: E402
from rio_cogeo.cogeo import cog_translate  # noqa: E402
from rio_cogeo.profiles import cog_profiles  # noqa: E402

from reis import validate
from reis.catalog import CatalogGraph
from reis.data import (
    DAT_CHECKSUM,
    DAT_COG,
    DAT_CONSISTENCY,
    DAT_FORMAT,
    DAT_SIZE,
    validate_data,
)
from tests.conftest import CatalogBuilder, mutate_json

pytestmark = pytest.mark.integration

_BBOX = [4.0, 50.0, 6.0, 52.0]
_PARQUET_TYPE = "application/vnd.apache.parquet"
_COG_TYPE = "image/tiff; application=geotiff; profile=cloud-optimized"
_TIFF_TYPE = "image/tiff; application=geotiff"


def _multihash(payload: bytes) -> str:
    return "1220" + hashlib.sha256(payload).hexdigest()


def _asset(href: str, media_type: str) -> dict[str, Any]:
    return {"href": href, "type": media_type, "roles": ["data"]}


def _write_geoparquet(path: Path) -> None:
    minx, miny, maxx, maxy = _BBOX
    points = [(minx, miny), (5.0, 51.0), (maxx, maxy)]
    wkb = [struct.pack("<BIdd", 1, 1, x, y) for x, y in points]
    table = pa.table({"geometry": pa.array(wkb, type=pa.binary()), "value": [1, 2, 3]})
    geo = {
        "version": "1.1.0",
        "primary_column": "geometry",
        "columns": {
            "geometry": {
                "encoding": "WKB",
                "geometry_types": ["Point"],
                "crs": json.loads(CRS.from_epsg(4326).to_json()),
                "bbox": [minx, miny, maxx, maxy],
            }
        },
    }
    table = table.replace_schema_metadata({b"geo": json.dumps(geo).encode()})
    pq.write_table(table, path)


def _write_plain_tiff(path: Path) -> None:
    # 1024px striped (untiled): a real GeoTIFF that rio-cogeo rejects as a COG,
    # since above 512px it requires internal tiling. The translated COG below is
    # built from this same source and does pass.
    minx, miny, maxx, maxy = _BBOX
    size = 1024
    data = (np.arange(size * size, dtype="uint8") % 251).reshape(1, size, size)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=size,
        width=size,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_bounds(minx, miny, maxx, maxy, size, size),
    ) as dst:
        dst.write(data)


def _write_cog(plain: Path, cog: Path) -> None:
    cog_translate(plain, cog, cog_profiles.get("deflate"), quiet=True)


def _patch_checksum(item_json: Path, asset_path: Path) -> None:
    payload = asset_path.read_bytes()
    mutate_json(
        item_json,
        lambda d: d["assets"]["data"].update(
            {"file:size": len(payload), "file:checksum": _multihash(payload)}
        ),
    )


def _build(root: Path) -> Path:
    cat = CatalogBuilder(root)
    col = cat.collection("layers")
    col.item("points", assets={"data": _asset("./points.parquet", _PARQUET_TYPE)})
    col.item("raster", assets={"data": _asset("./cog.tif", _COG_TYPE)})
    col.item("plain", assets={"data": _asset("./plain.tif", _TIFF_TYPE)})
    cat.write()

    layers = root / "layers"
    _write_geoparquet(layers / "points" / "points.parquet")
    _write_plain_tiff(layers / "raster" / "_src.tif")
    _write_cog(layers / "raster" / "_src.tif", layers / "raster" / "cog.tif")
    (layers / "raster" / "_src.tif").unlink()
    _write_plain_tiff(layers / "plain" / "plain.tif")

    _patch_checksum(layers / "points" / "points.json", layers / "points" / "points.parquet")
    _patch_checksum(layers / "raster" / "raster.json", layers / "raster" / "cog.tif")
    _patch_checksum(layers / "plain" / "plain.json", layers / "plain" / "plain.tif")
    return root


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _build(tmp_path_factory.mktemp("data") / "catalog")


@pytest.fixture
def catalog_root(pristine: Path, tmp_path: Path) -> Path:
    dst = tmp_path / "catalog"
    shutil.copytree(pristine, dst)
    return dst


def _data_findings(root: Path) -> list:
    return validate_data(CatalogGraph.load(root))


def _item(root: Path, name: str) -> Path:
    return root / "layers" / name / f"{name}.json"


def test_pristine_catalog_is_clean(catalog_root: Path) -> None:
    findings = _data_findings(catalog_root)
    assert findings == [], [f"{f.rule_id} {f.message}" for f in findings]


def test_pristine_passes_full_validate(catalog_root: Path) -> None:
    report = validate(catalog_root, data=True)
    assert report.passed
    assert not any(f.rule_id.startswith("PTL-DAT") for f in report.findings)


def test_wrong_checksum_flags_dat_001(catalog_root: Path) -> None:
    # sha256 of empty bytes: well-formed, but not this file's digest.
    empty = "1220" + hashlib.sha256(b"").hexdigest()
    mutate_json(
        _item(catalog_root, "points"),
        lambda d: d["assets"]["data"].__setitem__("file:checksum", empty),
    )
    ids = [f.rule_id for f in _data_findings(catalog_root)]
    assert DAT_CHECKSUM in ids


def test_wrong_size_flags_dat_002(catalog_root: Path) -> None:
    mutate_json(
        _item(catalog_root, "points"), lambda d: d["assets"]["data"].__setitem__("file:size", 7)
    )
    ids = [f.rule_id for f in _data_findings(catalog_root)]
    assert DAT_SIZE in ids


def test_wrong_media_type_flags_dat_003(catalog_root: Path) -> None:
    mutate_json(
        _item(catalog_root, "points"),
        lambda d: d["assets"]["data"].__setitem__("type", "application/vnd.pmtiles"),
    )
    findings = _data_findings(catalog_root)
    assert DAT_FORMAT in [f.rule_id for f in findings]


def test_non_cog_declared_cog_flags_dat_004(catalog_root: Path) -> None:
    # The plain GeoTIFF is a real TIFF but not cloud-optimized; declare it a COG.
    mutate_json(
        _item(catalog_root, "plain"), lambda d: d["assets"]["data"].__setitem__("type", _COG_TYPE)
    )
    findings = _data_findings(catalog_root)
    dat004 = [f for f in findings if f.rule_id == DAT_COG]
    assert dat004, [f.rule_id for f in findings]
    assert dat004[0].severity.value == "warning"


def test_bbox_disagreement_flags_dat_005(catalog_root: Path) -> None:
    mutate_json(
        _item(catalog_root, "points"), lambda d: d.__setitem__("bbox", [10.0, 60.0, 12.0, 62.0])
    )
    findings = _data_findings(catalog_root)
    dat005 = [f for f in findings if f.rule_id == DAT_CONSISTENCY]
    assert dat005
    assert dat005[0].severity.value == "warning"


def test_proj_epsg_disagreement_flags_dat_005(catalog_root: Path) -> None:
    # Declare EPSG:3857 while the GeoParquet's data is EPSG:4326.
    mutate_json(
        _item(catalog_root, "points"), lambda d: d["assets"]["data"].__setitem__("proj:epsg", 3857)
    )
    findings = _data_findings(catalog_root)
    assert DAT_CONSISTENCY in [f.rule_id for f in findings]
