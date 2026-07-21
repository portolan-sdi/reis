from __future__ import annotations

import pytest

from reis import validate
from tests.conftest import CatalogBuilder, findings_for, mutate_json

pytestmark = pytest.mark.unit


def test_missing_agents_md(catalog: CatalogBuilder) -> None:
    root = catalog.write()
    (root / "AGENTS.md").unlink()
    findings = findings_for(validate(root), "PTL-FIL-001")
    assert len(findings) == 1
    assert "AGENTS.md" in findings[0].message


def test_missing_readme_in_nested_collection(catalog: CatalogBuilder) -> None:
    env = catalog.subcatalog("environment")
    env.collection("air-quality")
    root = catalog.write()
    (root / "environment" / "air-quality" / "README.md").unlink()
    findings = findings_for(validate(root), "PTL-FIL-001")
    assert len(findings) == 1
    assert findings[0].path == "environment/air-quality/collection.json"
    assert "README.md" in findings[0].message


def test_wrong_case_filename_is_reported(catalog: CatalogBuilder) -> None:
    root = catalog.write()
    (root / "README.md").rename(root / "readme.md")
    findings = findings_for(validate(root), "PTL-FIL-001")
    assert len(findings) == 1
    assert "case-sensitive" in findings[0].message
    assert "readme.md" in findings[0].message


def test_missing_agents_link(catalog: CatalogBuilder) -> None:
    root = catalog.write()
    mutate_json(
        root / "catalog.json",
        lambda d: d.__setitem__("links", [link for link in d["links"] if link["rel"] != "agents"]),
    )
    findings = findings_for(validate(root), "PTL-FIL-002")
    assert len(findings) == 1
    assert "missing rel:'agents'" in findings[0].message


def test_agents_link_with_wrong_type(catalog: CatalogBuilder) -> None:
    root = catalog.write()

    def set_type(d: dict) -> None:
        for link in d["links"]:
            if link["rel"] == "agents":
                link["type"] = "text/plain"

    mutate_json(root / "catalog.json", set_type)
    findings = findings_for(validate(root), "PTL-FIL-002")
    assert len(findings) == 1
    assert "text/markdown" in findings[0].message


def test_agents_link_to_wrong_file(catalog: CatalogBuilder) -> None:
    root = catalog.write()

    def retarget(d: dict) -> None:
        for link in d["links"]:
            if link["rel"] == "agents":
                link["href"] = "./README.md"

    mutate_json(root / "catalog.json", retarget)
    findings = findings_for(validate(root), "PTL-FIL-002")
    assert len(findings) == 1
    assert "does not resolve to the sibling AGENTS.md" in findings[0].message


def test_absolute_agents_href(catalog: CatalogBuilder) -> None:
    root = catalog.write()

    def absolutize(d: dict) -> None:
        for link in d["links"]:
            if link["rel"] == "agents":
                link["href"] = "https://example.org/AGENTS.md"

    mutate_json(root / "catalog.json", absolutize)
    findings = findings_for(validate(root), "PTL-FIL-002")
    assert len(findings) == 1
    assert "relative path" in findings[0].message


def test_missing_readme_link(catalog: CatalogBuilder) -> None:
    root = catalog.write()
    mutate_json(
        root / "catalog.json",
        lambda d: d.__setitem__(
            "links", [link for link in d["links"] if link["rel"] != "describedby"]
        ),
    )
    findings = findings_for(validate(root), "PTL-FIL-003")
    assert len(findings) == 1
    assert "missing rel:'describedby'" in findings[0].message
    assert "README.md" in findings[0].message


def test_readme_link_with_wrong_type(catalog: CatalogBuilder) -> None:
    root = catalog.write()

    def set_type(d: dict) -> None:
        for link in d["links"]:
            if link["rel"] == "describedby":
                link["type"] = "text/plain"

    mutate_json(root / "catalog.json", set_type)
    findings = findings_for(validate(root), "PTL-FIL-003")
    assert len(findings) == 1
    assert "text/markdown" in findings[0].message


def test_readme_link_to_wrong_file(catalog: CatalogBuilder) -> None:
    root = catalog.write()

    def retarget(d: dict) -> None:
        for link in d["links"]:
            if link["rel"] == "describedby":
                link["href"] = "./AGENTS.md"

    mutate_json(root / "catalog.json", retarget)
    findings = findings_for(validate(root), "PTL-FIL-003")
    assert len(findings) == 1
    assert "does not resolve to the sibling README.md" in findings[0].message


def test_absolute_readme_href(catalog: CatalogBuilder) -> None:
    root = catalog.write()

    def absolutize(d: dict) -> None:
        for link in d["links"]:
            if link["rel"] == "describedby":
                link["href"] = "https://example.org/README.md"

    mutate_json(root / "catalog.json", absolutize)
    findings = findings_for(validate(root), "PTL-FIL-003")
    assert len(findings) == 1
    assert "relative path" in findings[0].message


def test_readme_link_on_collection(catalog: CatalogBuilder) -> None:
    catalog.collection("roads")
    root = catalog.write()
    mutate_json(
        root / "roads" / "collection.json",
        lambda d: d.__setitem__(
            "links", [link for link in d["links"] if link["rel"] != "describedby"]
        ),
    )
    findings = findings_for(validate(root), "PTL-FIL-003")
    assert len(findings) == 1
    assert findings[0].path == "roads/collection.json"
