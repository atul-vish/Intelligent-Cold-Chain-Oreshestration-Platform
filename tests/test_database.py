"""Opt-in integration smoke tests for analytics tools backed by SQL Server.

These tests are intentionally skipped by default because they may connect to a
real database and depend on local credentials/network access.

To enable them in PowerShell from the repository root:
    $env:RUN_DATABASE_INTEGRATION = "1"
    python -m pytest tests/test_database.py -v

Then disable them again with:
    Remove-Item Env:RUN_DATABASE_INTEGRATION

A passing smoke test means the tool returned a non-empty result without raising;
it does not by itself prove the returned analytics are numerically correct.
"""

import os

import pytest


RUN_INTEGRATION = os.getenv("RUN_DATABASE_INTEGRATION", "").strip() == "1"


@pytest.fixture(scope="module")
def analytics_tools():
    if not RUN_INTEGRATION:
        pytest.skip(
            "Database integration tests are opt-in. Set "
            "RUN_DATABASE_INTEGRATION=1 to run them."
        )

    # Import only when opted in; this avoids loading database/provider setup
    # during normal unit-test collection.
    from src.agent_tools import (
        get_fleet_overview,
        get_temperature_distribution,
        get_risk_analysis,
        get_data_quality_report,
        get_historical_trends,
    )

    return [
        ("Fleet Overview", get_fleet_overview),
        ("Temperature Distribution", get_temperature_distribution),
        ("Risk Analysis", get_risk_analysis),
        ("Data Quality", get_data_quality_report),
        ("Historical Trends", get_historical_trends),
    ]


@pytest.mark.parametrize(
    "tool_name",
    [
        "Fleet Overview",
        "Temperature Distribution",
        "Risk Analysis",
        "Data Quality",
        "Historical Trends",
    ],
)
def test_analytics_tool_returns_nonempty_result(analytics_tools, tool_name):
    tools = dict(analytics_tools)
    result = tools[tool_name].invoke({})
    assert result is not None
    assert result != ""
