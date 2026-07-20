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
from reis.model import Finding, Report, Severity
from reis.runner import validate

__all__ = ["Finding", "Report", "RulesConfig", "Severity", "validate"]
