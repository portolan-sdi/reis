"""Rule abstraction for the metadata validation pass."""

from __future__ import annotations

from abc import ABC
from collections.abc import Iterable
from typing import ClassVar

from reis.catalog import CatalogGraph, Kind, Node
from reis.model import Finding, Severity


class Rule(ABC):
    """A single validation rule.

    A rule visits nodes of the kinds in ``kinds`` and yields zero or more
    findings per node; no findings means the node passes. A rule with
    ``kinds = ()`` is graph-level: it runs once via ``check_graph``.
    """

    id: ClassVar[str]
    default_severity: ClassVar[Severity]
    description: ClassVar[str]
    kinds: ClassVar[tuple[Kind, ...]] = ()

    def check(self, node: Node, graph: CatalogGraph) -> Iterable[Finding]:
        return ()

    def check_graph(self, graph: CatalogGraph) -> Iterable[Finding]:
        return ()

    def finding(
        self,
        node: Node,
        message: str,
        *,
        json_pointer: str | None = None,
        fix_hint: str | None = None,
    ) -> Finding:
        """Build a finding for ``node`` with this rule's id and severity."""
        return Finding(
            rule_id=self.id,
            severity=self.default_severity,
            message=message,
            path=str(node.path),
            object_id=node.id,
            json_pointer=json_pointer,
            fix_hint=fix_hint,
        )
