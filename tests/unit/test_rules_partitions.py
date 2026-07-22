"""Tests for PTL-PRT-001 — a partitioned collection must advertise a glob."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from reis import validate
from tests.conftest import CatalogBuilder, findings_for, mutate_json

pytestmark = pytest.mark.unit


def _collection(root: Path) -> Path:
    return root / "roads" / "collection.json"


def _built(catalog: CatalogBuilder) -> Path:
    catalog.collection("roads").item("seg1")
    return catalog.write()


def test_non_partitioned_collection_is_clean(catalog: CatalogBuilder) -> None:
    report = validate(_built(catalog))
    assert findings_for(report, "PTL-PRT-001") == []


def test_partitioned_without_glob_is_flagged(catalog: CatalogBuilder) -> None:
    root = _built(catalog)
    mutate_json(_collection(root), lambda d: d.__setitem__("partition:scheme", "hive"))
    report = validate(root)
    assert len(findings_for(report, "PTL-PRT-001")) == 1


def test_glob_in_description_satisfies(catalog: CatalogBuilder) -> None:
    root = _built(catalog)

    def mutate(data: dict[str, Any]) -> None:
        data["partition:scheme"] = "hive"
        data["description"] = "Buildings across partitions at s3://bucket/buildings/*.parquet"

    mutate_json(_collection(root), mutate)
    assert findings_for(validate(root), "PTL-PRT-001") == []


def test_glob_field_satisfies(catalog: CatalogBuilder) -> None:
    root = _built(catalog)

    def mutate(data: dict[str, Any]) -> None:
        data["partition:scheme"] = "hive"
        data["portolan:glob"] = "s3://bucket/buildings/*.parquet"

    mutate_json(_collection(root), mutate)
    assert findings_for(validate(root), "PTL-PRT-001") == []
