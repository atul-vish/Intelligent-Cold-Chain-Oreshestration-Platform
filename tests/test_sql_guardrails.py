"""Unit tests for SQL query guardrails.

Run from the repository root:
    python -m pytest tests/test_sql_guardrails.py -v

These assertions follow the existing call pattern in the project, where a
truthy validator result represents a rejection/error and a falsey result means
the validator accepted the query. If src.agent_tools uses a different return
contract, update these assertions to match that documented contract.
"""

import pytest


@pytest.fixture(scope="module")
def validators():
    # Lazy import keeps test collection independent of provider credentials
    # that may be checked when src.agent_tools is imported.
    from src.agent_tools import validate_select, validate_shipment_scope
    return validate_select, validate_shipment_scope


def test_read_only_fleet_query_is_accepted(validators):
    validate_select, _ = validators
    query = "SELECT COUNT_BIG(*) FROM FDE_VIEWS.VW_ACTIVE_FLEET"
    assert not validate_select(query)


def test_delete_statement_is_rejected(validators):
    validate_select, _ = validators
    query = "DELETE FROM FDE_VIEWS.VW_ACTIVE_FLEET"
    assert validate_select(query)


def test_unauthorized_raw_table_is_rejected(validators):
    validate_select, _ = validators
    query = "SELECT * FROM dbo.TBL_SC_FLEET_HIST_RAW"
    assert validate_select(query)


def test_shipment_scoped_select_is_accepted_by_select_validator(validators):
    validate_select, _ = validators
    query = (
        "SELECT * FROM FDE_VIEWS.VW_ACTIVE_FLEET "
        "WHERE Shipment_ID = 'SHP123'"
    )
    assert not validate_select(query)


def test_shipment_scope_validator_returns_a_defined_result(validators):
    _, validate_shipment_scope = validators
    query = (
        "SELECT * FROM FDE_VIEWS.VW_ACTIVE_FLEET "
        "WHERE Shipment_ID = 'SHP123'"
    )
    result = validate_shipment_scope(query)
    assert result is None or isinstance(result, (str, bool))
