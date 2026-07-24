"""reis — validator and linter for Portolan catalogs.

Usage:

    from reis import validate
    report = validate("path/to/catalog")
    if not report.passed:
        for finding in report.errors:
            print(finding.message)
"""

from __future__ import annotations

from reis.config import RulesConfig
from reis.data import validate_data
from reis.live import validate_live
from reis.model import Finding, Report, Severity
from reis.runner import validate
from reis.schema import validate_schema
from reis.structural import validate_structural

__all__ = [
    "Finding",
    "Report",
    "RulesConfig",
    "Severity",
    "validate",
    "validate_data",
    "validate_live",
    "validate_schema",
    "validate_structural",
]
