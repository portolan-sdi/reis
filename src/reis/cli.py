"""Thin Click CLI over the reis validation library.

Exit codes: 0 when validation passed, 1 when errors were found,
2 on usage errors (Click's default).
"""

from __future__ import annotations

import json as json_module
from pathlib import Path

import click

from reis.model import Report, Severity
from reis.runner import validate

_SEVERITY_TAGS = {
    Severity.ERROR: "error",
    Severity.WARNING: "warning",
    Severity.INFO: "info",
}


@click.group()
@click.version_option(package_name="reis")
def main() -> None:
    """reis — validator and linter for Portolan catalogs."""


@main.command()
@click.argument(
    "catalog_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True, help="Emit the report as JSON.")
@click.option(
    "--structural/--no-structural",
    default=True,
    help="Run the STAC 1.1.0 structural pass via stac-validator (needs network).",
)
@click.option(
    "--schema/--no-schema",
    "schema",
    default=False,
    help="Also validate against the canonical Portolan profile schema (needs network).",
)
@click.option(
    "--schema-uri",
    "schema_uri",
    default=None,
    help=(
        "Override the URL the schema pass validates against (implies --schema). "
        "Defaults to the canonical Portolan profile schema."
    ),
)
def check(
    catalog_path: Path,
    as_json: bool,
    structural: bool,
    schema: bool,
    schema_uri: str | None,
) -> None:
    """Validate CATALOG_PATH: the Portolan metadata pass, the STAC 1.1.0
    structural pass (unless --no-structural), and — with --schema — the
    canonical Portolan profile schema."""
    report = validate(
        catalog_path,
        structural=structural,
        schema=schema or schema_uri is not None,
        schema_uri=schema_uri,
    )
    if as_json:
        click.echo(json_module.dumps(report.to_dict(), indent=2))
    else:
        _print_human(report)
    raise SystemExit(0 if report.passed else 1)


def _print_human(report: Report) -> None:
    if not report.findings:
        click.echo(f"OK: {report.files_checked} files checked, no findings.")
        return
    current_path: str | None = None
    for finding in report.findings:
        if finding.path != current_path:
            current_path = finding.path
            click.echo(finding.path)
        tag = _SEVERITY_TAGS[finding.severity]
        click.echo(f"  {tag:<7} {finding.rule_id}  {finding.message}")
        if finding.fix_hint:
            click.echo(f"          hint: {finding.fix_hint}")
    click.echo(
        f"{len(report.errors)} error(s), {len(report.warnings)} warning(s),"
        f" {len(report.infos)} info(s) across {report.files_checked} files."
    )
