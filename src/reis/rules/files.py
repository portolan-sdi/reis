"""Required-file rules (spec: core.md, Core Structure / AGENTS.md / README.md).

Existence and linkage only; content grading is out of scope.
"""

from __future__ import annotations

from collections.abc import Iterable

from reis.catalog import CatalogGraph, Node, is_absolute_href
from reis.model import Finding, Severity
from reis.rule import Rule
from reis.rules._common import links_of

_REQUIRED = ("AGENTS.md", "README.md")


class RequiredFilesRule(Rule):
    """Every catalog and collection directory carries its required files."""

    id = "PTL-FIL-001"
    default_severity = Severity.ERROR
    description = "catalog and collection directories must contain AGENTS.md and README.md"
    kinds = ()  # graph-level: needs the directory listings

    def check_graph(self, graph: CatalogGraph) -> Iterable[Finding]:
        for node in graph.iter("catalog", "collection"):
            listing = graph.dir_listing.get(node.path.parent, set())
            for required in _REQUIRED:
                if required in listing:
                    continue
                message = f"directory is missing required file {required}"
                variant = next(
                    (name for name in listing if name.casefold() == required.casefold()), None
                )
                if variant is not None:
                    message += f" (found '{variant}'; filenames are case-sensitive)"
                yield Finding(
                    rule_id=self.id,
                    severity=self.default_severity,
                    message=message,
                    path=str(node.path),
                    object_id=node.id,
                )


class AgentsLinkRule(Rule):
    """AGENTS.md is referenced through a rel:'agents' markdown link."""

    id = "PTL-FIL-002"
    default_severity = Severity.ERROR
    description = "AGENTS.md must be linked with rel:'agents' and type text/markdown"
    kinds = ("catalog", "collection")

    def check(self, node: Node, graph: CatalogGraph) -> Iterable[Finding]:
        agents_links = [
            (index, link)
            for index, link in enumerate(links_of(node))
            if link.get("rel") == "agents"
        ]
        if not agents_links:
            yield self.finding(
                node,
                "missing rel:'agents' link to AGENTS.md",
                json_pointer="/links",
                fix_hint='add {"rel": "agents", "href": "./AGENTS.md", "type": "text/markdown"}',
            )
            return
        for index, link in agents_links:
            if link.get("type") != "text/markdown":
                yield self.finding(
                    node,
                    f"rel:'agents' link has type {link.get('type')!r}, expected 'text/markdown'",
                    json_pointer=f"/links/{index}/type",
                )
            href = link.get("href")
            expected = node.path.parent / "AGENTS.md"
            if not isinstance(href, str) or not href or is_absolute_href(href):
                yield self.finding(
                    node,
                    f"rel:'agents' link href must be a relative path, got {href!r}",
                    json_pointer=f"/links/{index}/href",
                )
                continue
            resolved = graph.resolve_path(node, href)
            if resolved != expected or not graph.file_exists(expected):
                yield self.finding(
                    node,
                    f"rel:'agents' link href '{href}' does not resolve to the sibling AGENTS.md",
                    json_pointer=f"/links/{index}/href",
                )
