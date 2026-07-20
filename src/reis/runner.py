"""Validation runner: build the graph, run the rules, produce a report."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from pathlib import Path

from reis.catalog import ROOT_CATALOG, CatalogGraph
from reis.config import RulesConfig
from reis.model import Finding, Report, Severity
from reis.rule import Rule

GEN_MISSING_ROOT = "PTL-GEN-000"
GEN_UNPARSEABLE = "PTL-GEN-001"


def validate(
    catalog_path: Path | str,
    rules: Sequence[Rule] | None = None,
    config: RulesConfig | None = None,
) -> Report:
    """Run the Portolan metadata validation pass over a local catalog tree."""
    if rules is None:
        from reis.rules import DEFAULT_RULES

        rules = DEFAULT_RULES
    config = config or RulesConfig()
    root = Path(catalog_path)

    if not root.is_dir():
        return Report(
            findings=[
                Finding(
                    rule_id=GEN_MISSING_ROOT,
                    severity=Severity.ERROR,
                    message=f"catalog root is not a directory: {root}",
                    path=".",
                )
            ]
        )

    graph = CatalogGraph.load(root)
    findings: list[Finding] = []

    root_node = graph.nodes.get(ROOT_CATALOG)
    if root_node is None or graph.root is None:
        detail = (
            f"root catalog.json cannot be parsed: {root_node.parse_error}"
            if root_node is not None and root_node.parse_error
            else "root catalog.json is missing or is not a STAC Catalog"
        )
        return Report(
            findings=[
                Finding(
                    rule_id=GEN_MISSING_ROOT,
                    severity=Severity.ERROR,
                    message=detail,
                    path=str(ROOT_CATALOG),
                )
            ],
            files_checked=len(graph.nodes),
        )

    for node in graph.iter():
        if node.parse_error is not None:
            findings.append(
                Finding(
                    rule_id=GEN_UNPARSEABLE,
                    severity=Severity.ERROR,
                    message=f"file is not valid JSON: {node.parse_error}",
                    path=str(node.path),
                )
            )

    for rule in rules:
        if rule.id in config.disabled:
            continue
        if not rule.kinds:
            findings.extend(rule.check_graph(graph))
            continue
        for node in graph.iter(*rule.kinds):
            if node.parse_error is not None:
                continue
            findings.extend(rule.check(node, graph))

    if config.severity_overrides:
        findings = [
            dataclasses.replace(f, severity=config.severity_overrides[f.rule_id])
            if f.rule_id in config.severity_overrides
            else f
            for f in findings
        ]

    findings.sort(key=lambda f: (f.path, f.rule_id, f.message))
    return Report(findings=findings, files_checked=len(graph.nodes))
