"""Pytest regression tests for the cold-chain orchestrator's intent routing.

Run from the repository root:
    python -m pytest tests/test_orchestrator_routing.py -v

These tests verify the current expected routing contract. If a test fails, inspect
classify_request() / get_tools_for_intent() rather than weakening the assertion.
"""

import pytest


@pytest.fixture(scope="module")
def orchestrator():
    # Import lazily so pytest can collect tests even if an optional runtime
    # integration (LLM/provider credentials) is not configured on this machine.
    from src import orchestrator as module
    return module


@pytest.mark.parametrize(
    ("user_text", "expected"),
    [
        (
            "What does the SOP say about temperature thresholds?",
            "policy_only",
        ),
        (
            "What actions should a dispatcher take if a shipment reaches 5.2°C?",
            "hypothetical_incident",
        ),
        (
            "What is the current temperature of shipment SHP123?",
            "shipment_investigation",
        ),
        (
            "Give me an overview of fleet temperature.",
            "fleet_overview",
        ),
        (
            "Show temperature distribution in bands.",
            "temperature_distribution",
        ),
        ("Give me a risk analysis.", "risk_analysis"),
        (
            "Run a data quality report for missing values and duplicates.",
            "data_quality",
        ),
        ("Show historical trends by year.", "historical_trends"),
        (
            "What are the weather conditions on this route at 37.7, -122.4?",
            "corridor_conditions",
        ),
        ("Explain what a vector database is.", "general"),
    ],
)
def test_classify_request(orchestrator, user_text, expected):
    assert orchestrator.classify_request(user_text) == expected


@pytest.mark.parametrize(
    ("intent", "user_text", "expected_tools"),
    [
        (
            "fleet_overview",
            "Summarize fleet temperature.",
            {"get_fleet_overview"},
        ),
        (
            "temperature_distribution",
            "Show temperature distribution.",
            {"get_temperature_distribution"},
        ),
        ("risk_analysis", "Give me a risk analysis.", {"get_risk_analysis"}),
        (
            "data_quality",
            "Run a data quality report.",
            {"get_data_quality_report"},
        ),
        (
            "historical_trends",
            "Show trends by year.",
            {"get_historical_trends"},
        ),
    ],
)
def test_deterministic_tool_routing(
    orchestrator, intent, user_text, expected_tools
):
    selected_tools = orchestrator.get_tools_for_intent(intent, user_text)
    actual_tools = {tool.name for tool in selected_tools}
    assert actual_tools == expected_tools


def test_shipment_investigation_fails_closed_without_identity_mapping(orchestrator):
    if orchestrator.SHIPMENT_IDENTITY_MAPPING_AVAILABLE:
        pytest.skip(
            "The identity mapping is enabled; update this test to verify the "
            "approved mapping and its access controls."
        )

    tools = orchestrator.get_tools_for_intent(
        "shipment_investigation",
        "What is the current temperature of shipment SHP123?",
    )
    assert tools == []
