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
_MARKDOWN = "text/markdown"


def _check_markdown_link(
    rule: Rule, node: Node, graph: CatalogGraph, *, rel: str, target: str
) -> Iterable[Finding]:
    """Findings for a required ``rel`` link pointing at a sibling markdown file.

    Shared by the AGENTS.md and README.md link rules: exactly one relative,
    ``text/markdown`` link that resolves to ``target`` in the object's own
    directory.
    """
    matches = [(index, link) for index, link in enumerate(links_of(node)) if link.get("rel") == rel]
    if not matches:
        yield rule.finding(
            node,
            f"missing rel:{rel!r} link to {target}",
            json_pointer="/links",
            fix_hint=f'add {{"rel": "{rel}", "href": "./{target}", "type": "text/markdown"}}',
        )
        return
    expected = node.path.parent / target
    for index, link in matches:
        if link.get("type") != _MARKDOWN:
            yield rule.finding(
                node,
                f"rel:{rel!r} link has type {link.get('type')!r}, expected 'text/markdown'",
                json_pointer=f"/links/{index}/type",
            )
        href = link.get("href")
        if not isinstance(href, str) or not href or is_absolute_href(href):
            yield rule.finding(
                node,
                f"rel:{rel!r} link href must be a relative path, got {href!r}",
                json_pointer=f"/links/{index}/href",
            )
            continue
        resolved = graph.resolve_path(node, href)
        if resolved != expected or not graph.file_exists(expected):
            yield rule.finding(
                node,
                f"rel:{rel!r} link href {href!r} does not resolve to the sibling {target}",
                json_pointer=f"/links/{index}/href",
            )


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
        yield from _check_markdown_link(self, node, graph, rel="agents", target="AGENTS.md")


class ReadmeLinkRule(Rule):
    """README.md is referenced through a rel:'describedby' markdown link."""

    id = "PTL-FIL-003"
    default_severity = Severity.ERROR
    description = "README.md must be linked with rel:'describedby' and type text/markdown"
    kinds = ("catalog", "collection")

    def check(self, node: Node, graph: CatalogGraph) -> Iterable[Finding]:
        yield from _check_markdown_link(self, node, graph, rel="describedby", target="README.md")
