"""Conformance-declaration rules (spec: core.md, Conformance and Versioning)."""

from __future__ import annotations

import re
from collections.abc import Iterable

from reis.catalog import CatalogGraph, Node
from reis.model import Finding, Severity
from reis.rule import Rule

SCHEMA_URI_PATTERN = re.compile(
    r"^https://portolan-sdi\.github\.io/portolan-spec/portolan/v\d+\.\d+\.\d+/schema\.json$"
)


def declared_schema_uris(node: Node) -> list[str]:
    raw = node.data.get("stac_extensions")
    if not isinstance(raw, list):
        return []
    return [uri for uri in raw if isinstance(uri, str) and SCHEMA_URI_PATTERN.match(uri)]


class SchemaUriDeclaredRule(Rule):
    """Every catalog and collection declares exactly one Portolan schema URI."""

    id = "PTL-CNF-001"
    default_severity = Severity.ERROR
    description = "catalogs and collections must declare the versioned Portolan schema URI"
    kinds = ("catalog", "collection")

    def check(self, node: Node, graph: CatalogGraph) -> Iterable[Finding]:
        uris = declared_schema_uris(node)
        if not uris:
            yield self.finding(
                node,
                "stac_extensions declares no Portolan schema URI",
                json_pointer="/stac_extensions",
                fix_hint=(
                    "add e.g. https://portolan-sdi.github.io/portolan-spec"
                    "/portolan/v0.1.0/schema.json"
                ),
            )
        elif len(uris) > 1:
            yield self.finding(
                node,
                f"stac_extensions declares {len(uris)} Portolan schema URIs; exactly one expected",
                json_pointer="/stac_extensions",
            )


class SchemaUriConsistencyRule(Rule):
    """All objects declare the root catalog's schema URI.

    The spec makes declaring the URI a MUST but explicitly downgrades a
    mismatch with the root to a warning: a mixed-version catalog remains
    valid.
    """

    id = "PTL-CNF-002"
    default_severity = Severity.WARNING
    description = "objects whose Portolan schema URI differs from the root's are flagged"
    kinds = ()  # graph-level: compares everything against the root

    def check_graph(self, graph: CatalogGraph) -> Iterable[Finding]:
        root = graph.root
        if root is None:
            return
        root_uris = declared_schema_uris(root)
        if len(root_uris) != 1:
            return  # PTL-CNF-001 reports the root's own problem
        root_uri = root_uris[0]
        for node in graph.iter("catalog", "collection"):
            if node is root:
                continue
            uris = declared_schema_uris(node)
            if len(uris) != 1:
                continue  # PTL-CNF-001 reports missing/ambiguous declarations
            if uris[0] != root_uri:
                yield Finding(
                    rule_id=self.id,
                    severity=self.default_severity,
                    message=(
                        f"declared schema URI {uris[0]} differs from the root catalog's {root_uri}"
                    ),
                    path=str(node.path),
                    object_id=node.id,
                    json_pointer="/stac_extensions",
                )
