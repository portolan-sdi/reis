"""Byte-level checks: does an asset's data match what its metadata declares?

Reached only through :func:`reis.data.default_validator`, so importing this
module (and the geospatial stack it pulls) happens only when the opt-in data
pass actually runs. Each check turns a divergence between the declared metadata
and the real bytes into a :class:`reis.data.DataDefect`:

- ``PTL-DAT-001`` recomputed multihash ≠ ``file:checksum`` (MUST)
- ``PTL-DAT-002`` byte length ≠ ``file:size`` (MUST)
- ``PTL-DAT-003`` magic bytes ≠ declared media type (MUST)
- ``PTL-DAT-004`` declared cloud-optimized COG that is not one (advisory)
- ``PTL-DAT-005`` actual bbox/CRS inconsistent with the declared metadata (advisory)

Checks that cannot run for a given asset — bytes unreachable, an unsupported
hash function, an unreadable header — degrade to an INFO or to silence rather
than a false ERROR; a present-but-unverifiable checksum is not a conformance
failure the way a wrong one is.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from typing import Any

import pyarrow.parquet as pq
import rasterio
from pyproj import CRS, Transformer
from rio_cogeo.cogeo import cog_validate

from reis._multihash import decode_multihash
from reis.catalog import Node
from reis.data import (
    DAT_CHECKSUM,
    DAT_COG,
    DAT_CONSISTENCY,
    DAT_FORMAT,
    DAT_SIZE,
    DataDefect,
)
from reis.data.reader import AssetReader, Locator
from reis.model import Severity

# Multihash function code -> hashlib algorithm name.
_HASH_ALGOS = {
    0x11: "sha1",
    0x12: "sha256",
    0x13: "sha512",
    0x14: "sha3_512",
    0x15: "sha3_384",
    0x16: "sha3_256",
    0x17: "sha3_224",
}

# Recognized formats: (magic-byte probe, media-type marker).
_PMTILES_MAGIC = b"PMTiles"
_HEAD_BYTES = 16  # enough for every magic-number probe below

# bbox comparison tolerance in degrees (~1 km); absorbs rounding and
# reprojection gridding so only genuine divergence trips PTL-DAT-005.
_BBOX_TOL = 0.01


@dataclass(frozen=True)
class _Geo:
    """Actual spatial metadata read from an asset's bytes."""

    bbox: list[float] | None
    epsg: int | None
    crs: Any | None  # pyproj CRS, when EPSG alone doesn't capture it


def check_node(node: Node, reader: AssetReader) -> list[DataDefect]:
    """Verify every asset on ``node`` against its declared metadata."""
    defects: list[DataDefect] = []
    for key, asset in _assets_of(node):
        href = asset.get("href")
        if not isinstance(href, str) or not href:
            continue  # PTL-AST-001 reports a missing href
        defects.extend(_check_asset(node, key, asset, href, reader))
    return defects


def _assets_of(node: Node) -> list[tuple[str, dict[str, Any]]]:
    assets = node.data.get("assets")
    if not isinstance(assets, dict):
        return []
    return [(key, asset) for key, asset in assets.items() if isinstance(asset, dict)]


def _check_asset(
    node: Node, key: str, asset: dict[str, Any], href: str, reader: AssetReader
) -> list[DataDefect]:
    defects: list[DataDefect] = []
    media_type = asset.get("type")
    expected = _expected_format(media_type) if isinstance(media_type, str) else None

    defects.extend(_check_bytes(key, asset, href, expected, node, reader))

    located = reader.locate(node, href)
    if located is None:
        return defects
    if expected == "tiff" and _is_cloud_optimized(media_type):
        defects.extend(_check_cog(key, located))
    if expected in {"parquet", "tiff", "pmtiles"}:
        defects.extend(_check_consistency(node, key, asset, expected, located))
    return defects


def _check_bytes(
    key: str,
    asset: dict[str, Any],
    href: str,
    expected: str | None,
    node: Node,
    reader: AssetReader,
) -> list[DataDefect]:
    """Stream the object once: verify checksum, size, and format magic."""
    stream = reader.stream(node, href)
    if stream is None:
        return []  # not fetchable; metadata pass owns missing/foreign hrefs

    declared_checksum = asset.get("file:checksum")
    decoded = decode_multihash(declared_checksum)
    algo: str | None = None
    hasher: Any = None
    if decoded is not None:
        code, digest = decoded
        algo = _HASH_ALGOS.get(code)
        if algo is not None:
            hasher = hashlib.new(algo)

    head = b""
    count = 0
    try:
        for chunk in stream:
            count += len(chunk)
            if len(head) < _HEAD_BYTES:
                head += chunk[: _HEAD_BYTES - len(head)]
            if hasher is not None:
                hasher.update(chunk)
    except OSError as exc:
        return [
            DataDefect(
                DAT_CHECKSUM,
                Severity.INFO,
                f"asset '{key}' bytes could not be read ({exc}); not verified",
                key,
            )
        ]

    defects: list[DataDefect] = []
    defects.extend(_verify_checksum(key, decoded, algo, hasher))
    defects.extend(_verify_size(key, asset.get("file:size"), count))
    defects.extend(_verify_format(key, expected, head))
    return defects


def _verify_checksum(
    key: str,
    decoded: tuple[int, bytes] | None,
    algo: str | None,
    hasher: Any,
) -> list[DataDefect]:
    if decoded is None:
        return []  # absent or malformed: PTL-AST-003/004 own that
    if algo is None:
        code = decoded[0]
        return [
            DataDefect(
                DAT_CHECKSUM,
                Severity.INFO,
                f"asset '{key}' file:checksum uses hash function 0x{code:x}, "
                "which reis cannot compute; not verified",
                key,
                "file:checksum",
            )
        ]
    if hasher.digest() != decoded[1]:
        return [
            DataDefect(
                DAT_CHECKSUM,
                Severity.ERROR,
                f"asset '{key}' file:checksum does not match the bytes "
                f"(declared {hasher.name} digest differs from recomputed)",
                key,
                "file:checksum",
            )
        ]
    return []


def _verify_size(key: str, declared: Any, count: int) -> list[DataDefect]:
    if isinstance(declared, bool) or not isinstance(declared, int):
        return []  # absent or non-integer: PTL-AST-003 owns that
    if declared != count:
        return [
            DataDefect(
                DAT_SIZE,
                Severity.ERROR,
                f"asset '{key}' file:size is {declared} but the bytes are {count}",
                key,
                "file:size",
            )
        ]
    return []


def _verify_format(key: str, expected: str | None, head: bytes) -> list[DataDefect]:
    if expected is None:
        return []
    actual = _detect_format(head)
    if actual is None or actual == expected:
        return []
    return [
        DataDefect(
            DAT_FORMAT,
            Severity.ERROR,
            f"asset '{key}' declares {expected} but its bytes are {actual}",
            key,
            "type",
        )
    ]


def _check_cog(key: str, located: Locator) -> list[DataDefect]:
    try:
        is_valid, errors, _warnings = cog_validate(located.gdal_path(), quiet=True)
    except Exception as exc:  # noqa: BLE001 - a reader failure is not a conformance fault
        return [
            DataDefect(
                DAT_COG,
                Severity.INFO,
                f"asset '{key}' could not be checked for cloud-optimization ({exc})",
                key,
            )
        ]
    if is_valid and not errors:
        return []
    reason = errors[0] if errors else "not a cloud-optimized GeoTIFF"
    return [
        DataDefect(
            DAT_COG,
            Severity.WARNING,
            f"asset '{key}' declares a cloud-optimized COG but is not one: {reason}",
            key,
            "type",
        )
    ]


def _check_consistency(
    node: Node, key: str, asset: dict[str, Any], expected: str, located: Locator
) -> list[DataDefect]:
    try:
        geo = _extract_geo(expected, located)
    except Exception as exc:  # noqa: BLE001 - unreadable header is advisory, not fatal
        return [
            DataDefect(
                DAT_CONSISTENCY,
                Severity.INFO,
                f"asset '{key}' spatial metadata could not be read ({exc})",
                key,
            )
        ]
    if geo is None:
        return []

    defects: list[DataDefect] = []
    declared_epsg = _declared_epsg(node, asset)
    if declared_epsg is not None and geo.epsg is not None and declared_epsg != geo.epsg:
        defects.append(
            DataDefect(
                DAT_CONSISTENCY,
                Severity.WARNING,
                f"asset '{key}' declares proj:epsg {declared_epsg} but its data is EPSG:{geo.epsg}",
                key,
            )
        )

    declared_bbox = _declared_bbox(node)
    actual_wgs84 = _to_wgs84(geo)
    if declared_bbox is not None and actual_wgs84 is not None:
        if not _bbox_close(declared_bbox, actual_wgs84):
            defects.append(
                DataDefect(
                    DAT_CONSISTENCY,
                    Severity.WARNING,
                    f"asset '{key}' data bbox {_fmt_bbox(actual_wgs84)} does not match the "
                    f"declared bbox {_fmt_bbox(declared_bbox)}",
                    key,
                )
            )
    return defects


# --- format probing --------------------------------------------------------


def _expected_format(media_type: str) -> str | None:
    lowered = media_type.lower()
    if "parquet" in lowered:
        return "parquet"
    if lowered.startswith("image/tiff"):
        return "tiff"
    if "pmtiles" in lowered:
        return "pmtiles"
    if lowered.startswith("image/png"):
        return "png"
    if lowered.startswith("image/jpeg") or lowered.startswith("image/jpg"):
        return "jpeg"
    return None


def _is_cloud_optimized(media_type: Any) -> bool:
    return isinstance(media_type, str) and "cloud-optimized" in media_type.lower()


def _detect_format(head: bytes) -> str | None:
    if head[:4] == b"PAR1":
        return "parquet"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if head[: len(_PMTILES_MAGIC)] == _PMTILES_MAGIC:
        return "pmtiles"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    return None


# --- spatial extraction ----------------------------------------------------


def _extract_geo(expected: str, located: Locator) -> _Geo | None:
    if expected == "parquet":
        return _geo_from_parquet(located)
    if expected == "tiff":
        return _geo_from_raster(located)
    if expected == "pmtiles":
        return _geo_from_pmtiles(located)
    return None


def _geo_from_parquet(located: Locator) -> _Geo | None:
    source: Any = located.open_binary() if located.is_remote else located.source
    parquet = pq.ParquetFile(source)
    raw = (parquet.schema_arrow.metadata or {}).get(b"geo")
    if raw is None:
        return None
    geo = json.loads(raw)
    primary = geo.get("primary_column")
    column = geo.get("columns", {}).get(primary, {})
    bbox = column.get("bbox")
    crs_obj = column.get("crs")
    crs = CRS.from_user_input(crs_obj) if crs_obj is not None else CRS.from_epsg(4326)
    return _Geo(bbox=_as_bbox(bbox), epsg=crs.to_epsg(), crs=crs)


def _geo_from_raster(located: Locator) -> _Geo | None:
    with rasterio.open(located.gdal_path()) as src:
        bounds = src.bounds
        crs = CRS.from_wkt(src.crs.to_wkt()) if src.crs else None
        return _Geo(
            bbox=[bounds.left, bounds.bottom, bounds.right, bounds.top],
            epsg=crs.to_epsg() if crs else None,
            crs=crs,
        )


def _geo_from_pmtiles(located: Locator) -> _Geo | None:
    with located.open_binary() as handle:
        header = handle.read(127)
    if len(header) < 127 or header[:7] != _PMTILES_MAGIC:
        return None
    # v3 header: min/max lon/lat are int32 E7 at byte offsets 102, 106, 110, 114.
    min_lon, min_lat, max_lon, max_lat = struct.unpack_from("<iiii", header, 102)
    bbox = [min_lon / 1e7, min_lat / 1e7, max_lon / 1e7, max_lat / 1e7]
    return _Geo(bbox=bbox, epsg=4326, crs=CRS.from_epsg(4326))


def _as_bbox(bbox: Any) -> list[float] | None:
    if not isinstance(bbox, list) or len(bbox) < 4:
        return None
    try:
        values = [float(v) for v in bbox]
    except (TypeError, ValueError):
        return None
    # Drop any z coordinates: [minx, miny, (minz,) maxx, maxy, (maxz)].
    if len(values) == 6:
        return [values[0], values[1], values[3], values[4]]
    return values[:4]


def _to_wgs84(geo: _Geo) -> list[float] | None:
    if geo.bbox is None:
        return None
    if geo.crs is None or geo.epsg == 4326:
        return geo.bbox
    transformer = Transformer.from_crs(geo.crs, CRS.from_epsg(4326), always_xy=True)
    minx, miny, maxx, maxy = geo.bbox
    xs: list[float] = []
    ys: list[float] = []
    # Sample the four corners; a rectangle in a projected CRS is not a rectangle
    # in WGS84, so corners bound the reprojected extent well enough for the tol.
    for x, y in ((minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)):
        lon, lat = transformer.transform(x, y)
        xs.append(lon)
        ys.append(lat)
    return [min(xs), min(ys), max(xs), max(ys)]


def _bbox_close(a: list[float], b: list[float]) -> bool:
    return all(abs(x - y) <= _BBOX_TOL for x, y in zip(a[:4], b[:4], strict=False))


def _fmt_bbox(bbox: list[float]) -> str:
    return "[" + ", ".join(f"{v:.4f}" for v in bbox[:4]) + "]"


def _declared_bbox(node: Node) -> list[float] | None:
    if node.kind == "item":
        return _as_bbox(node.data.get("bbox"))
    extent = node.data.get("extent", {})
    spatial = extent.get("spatial", {}) if isinstance(extent, dict) else {}
    boxes = spatial.get("bbox") if isinstance(spatial, dict) else None
    if isinstance(boxes, list) and boxes:
        return _as_bbox(boxes[0])
    return None


def _declared_epsg(node: Node, asset: dict[str, Any]) -> int | None:
    for source in (asset, node.data.get("properties", {}), node.data):
        if isinstance(source, dict):
            value = source.get("proj:epsg")
            if isinstance(value, int) and not isinstance(value, bool):
                return value
    return None
