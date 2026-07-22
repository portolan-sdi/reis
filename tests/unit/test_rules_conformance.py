from __future__ import annotations

import pytest

from reis import validate
from reis.model import Severity
from tests.conftest import PORTOLAN_URI, CatalogBuilder, findings_for, mutate_json

pytestmark = pytest.mark.unit


def test_missing_schema_uri(catalog: CatalogBuilder) -> None:
    catalog.collection("roads")
    root = catalog.write()
    mutate_json(root / "roads" / "collection.json", lambda d: d.pop("stac_extensions"))
    findings = findings_for(validate(root), "PTL-CNF-001")
    assert len(findings) == 1
    assert findings[0].path == "roads/collection.json"


def test_wrong_host_uri_is_not_recognized(catalog: CatalogBuilder) -> None:
    root = catalog.write()
    mutate_json(
        root / "catalog.json",
        lambda d: d.__setitem__(
            "stac_extensions", ["https://example.org/portolan/v0.1.0/schema.json"]
        ),
    )
    findings = findings_for(validate(root), "PTL-CNF-001")
    assert len(findings) == 1


def test_two_portolan_uris_on_one_object(catalog: CatalogBuilder) -> None:
    root = catalog.write()
    mutate_json(
        root / "catalog.json",
        lambda d: d.__setitem__(
            "stac_extensions",
            [
                PORTOLAN_URI,
                "https://schemas.portolan-sdi.org/portolan/v0.2.0/schema.json",
            ],
        ),
    )
    findings = findings_for(validate(root), "PTL-CNF-001")
    assert len(findings) == 1
    assert "exactly one" in findings[0].message


def test_other_extensions_alongside_portolan_pass(catalog: CatalogBuilder) -> None:
    root = catalog.write()
    mutate_json(
        root / "catalog.json",
        lambda d: d.__setitem__(
            "stac_extensions",
            [PORTOLAN_URI, "https://stac-extensions.github.io/file/v2.1.0/schema.json"],
        ),
    )
    assert findings_for(validate(root), "PTL-CNF-001") == []


def test_version_mismatch_with_root_is_warning(catalog: CatalogBuilder) -> None:
    catalog.collection("roads")
    root = catalog.write()
    mutate_json(
        root / "roads" / "collection.json",
        lambda d: d.__setitem__(
            "stac_extensions",
            ["https://schemas.portolan-sdi.org/portolan/v0.2.0/schema.json"],
        ),
    )
    report = validate(root)
    findings = findings_for(report, "PTL-CNF-002")
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert "v0.2.0" in findings[0].message
    assert report.passed  # a mixed-version catalog remains valid


def test_missing_uri_does_not_also_trigger_mismatch(catalog: CatalogBuilder) -> None:
    catalog.collection("roads")
    root = catalog.write()
    mutate_json(root / "roads" / "collection.json", lambda d: d.pop("stac_extensions"))
    report = validate(root)
    assert findings_for(report, "PTL-CNF-002") == []
