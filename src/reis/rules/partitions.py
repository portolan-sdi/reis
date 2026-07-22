"""Partition rules (spec: formats.md, Partitioned Collections).

A collection that splits its data across partition files MUST advertise a glob
pattern so a consumer can read every partition with one URL, rather than
enumerating items (formats.md:76-83). A collection is taken to be partitioned
when it declares any ``partition:*`` field — the signal the Portolan partition
extension writes.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from reis.catalog import CatalogGraph, Node
from reis.model import Finding, Severity
from reis.rule import Rule


class PartitionGlobRule(Rule):
    """A partitioned collection MUST advertise a glob pattern for its partitions."""

    id = "PTL-PRT-001"
    default_severity = Severity.ERROR
    description = "a partitioned collection must advertise a glob pattern for its partitions"
    kinds = ("collection",)

    def check(self, node: Node, graph: CatalogGraph) -> Iterable[Finding]:
        if not _is_partitioned(node):
            return
        if _has_glob(node):
            return
        yield self.finding(
            node,
            "partitioned collection declares no glob pattern for accessing its partitions",
            json_pointer="/description",
            fix_hint="add a glob to the description, e.g. 's3://bucket/data/*.parquet'",
        )


def _is_partitioned(node: Node) -> bool:
    return any(key.startswith("partition:") for key in node.data)


def _has_glob(node: Node) -> bool:
    description = node.data.get("description")
    if isinstance(description, str) and "*" in description:
        return True
    return any(isinstance(value, str) and "*" in value for key, value in _glob_fields(node))


def _glob_fields(node: Node) -> Iterable[tuple[str, Any]]:
    for key, value in node.data.items():
        if "glob" in key.lower():
            yield key, value
