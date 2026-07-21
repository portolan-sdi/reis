"""Validation runner: build the graph, run the rules, produce a report."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from reis.catalog import ROOT_CATALOG, CatalogGraph
from reis.config import RulesConfig
from reis.model import Finding, Report, Severity
from reis.rule import Rule
from reis.schema import SCH_INVALID, validate_schema
from reis.structural import STR_INVALID, validate_structural

GEN_MISSING_ROOT = "PTL-GEN-000"
GEN_UNPARSEABLE = "PTL-GEN-001"

_Validator = Callable[[dict[str, Any]], list[str]]


def _optional_passes(
    graph: CatalogGraph,
    config: RulesConfig,
    *,
    structural: bool,
    structural_validator: _Validator | None,
    schema: bool,
    schema_validator: _Validator | None,
) -> list[Finding]:
    """Run the opt-in structural and schema passes, honouring their disable ids."""
    findings: list[Finding] = []
    if structural and STR_INVALID not in config.disabled:
        findings.extend(validate_structural(graph, structural_validator))
    if schema and SCH_INVALID not in config.disabled:
        findings.extend(validate_schema(graph, schema_validator))
    return findings


def validate(
    catalog_path: Path | str,
    rules: Sequence[Rule] | None = None,
    config: RulesConfig | None = None,
    *,
    structural: bool = False,
    structural_validator: Callable[[dict[str, Any]], list[str]] | None = None,
    schema: bool = False,
    schema_validator: Callable[[dict[str, Any]], list[str]] | None = None,
) -> Report:
    """Validate a local Portolan catalog tree.

    The metadata pass always runs. When ``structural`` is true the STAC 1.1.0
    structural pass runs too, delegated to stac-validator (see
    :mod:`reis.structural`); it is off by default here because it reaches the
    network, and on by default in the CLI. Disabling ``PTL-STR-001`` via
    ``config`` skips the structural pass. ``structural_validator`` injects an
    alternate validator, chiefly for offline testing.

    When ``schema`` is true the Portolan profile schema pass runs too, applying
    the published JSON Schema to every object (see :mod:`reis.schema`); it is
    off by default because it reaches the network and overlaps the metadata
    pass. Disabling ``PTL-SCH-001`` via ``config`` skips it. ``schema_validator``
    injects an alternate validator, chiefly for offline testing.
    """
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

    findings.extend(
        _optional_passes(
            graph,
            config,
            structural=structural,
            structural_validator=structural_validator,
            schema=schema,
            schema_validator=schema_validator,
        )
    )

    if config.severity_overrides:
        findings = [
            dataclasses.replace(f, severity=config.severity_overrides[f.rule_id])
            if f.rule_id in config.severity_overrides
            else f
            for f in findings
        ]

    findings.sort(key=lambda f: (f.path, f.rule_id, f.message))
    return Report(findings=findings, files_checked=len(graph.nodes))
