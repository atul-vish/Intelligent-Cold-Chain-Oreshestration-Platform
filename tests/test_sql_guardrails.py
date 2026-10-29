import pytest

from src.agent_tools import validate_select


# --------------------------------------------------
# 1. ALLOWED SQL QUERIES
# --------------------------------------------------

@pytest.mark.parametrize(
    "query",
    [
        "SELECT 1",
        "SELECT COUNT(*) FROM FDE_VIEWS.VW_ACTIVE_FLEET",
        """
        SELECT
            Risk_Classification,
            COUNT(*) AS Record_Count
        FROM FDE_VIEWS.VW_ACTIVE_FLEET
        GROUP BY Risk_Classification
        """,
        """
        SELECT AVG(Delay_Probability) AS Avg_Delay
        FROM FDE_VIEWS.VW_ACTIVE_FLEET;
        """,
    ],
)
def test_valid_select_queries_are_allowed(query):
    """Ordinary read-only SELECT queries should pass validation."""
    assert validate_select(query) is None


# --------------------------------------------------
# 2. BLOCK WRITE AND ADMINISTRATIVE OPERATIONS
# --------------------------------------------------

@pytest.mark.parametrize(
    "query",
    [
        "INSERT INTO test_table VALUES (1)",
        "UPDATE test_table SET value = 1",
        "DELETE FROM test_table",
        "DROP TABLE test_table",
        "ALTER TABLE test_table ADD value INT",
        "CREATE TABLE test_table (id INT)",
        "TRUNCATE TABLE test_table",
        "MERGE INTO test_table USING source_table ON 1 = 1 "
        "WHEN MATCHED THEN DELETE",
        "EXEC sp_help",
        "GRANT SELECT ON test_table TO public",
    ],
)
def test_write_and_admin_queries_are_blocked(query):
    """Database modifications and administrative commands must be rejected."""
    result = validate_select(query)

    assert result is not None
    assert result.startswith("SECURITY BLOCK:")


# --------------------------------------------------
# 3. BLOCK MULTIPLE SQL STATEMENTS
# --------------------------------------------------

@pytest.mark.parametrize(
    "query",
    [
        "SELECT 1; DROP TABLE test_table",
        "SELECT 1; DELETE FROM test_table",
        "SELECT 1; UPDATE test_table SET value = 2",
    ],
)
def test_multiple_statements_are_blocked(query):
    """A SELECT must not be combined with another SQL statement."""
    result = validate_select(query)

    assert result is not None
    assert result.startswith("SECURITY BLOCK:")


# --------------------------------------------------
# 4. BLOCK SQL COMMENTS
# --------------------------------------------------

@pytest.mark.parametrize(
    "query",
    [
        "SELECT 1 -- bypass attempt",
        "SELECT 1 /* bypass attempt */",
    ],
)
def test_sql_comments_are_blocked(query):
    """SQL comments must be rejected by the current policy."""
    result = validate_select(query)

    assert result is not None
    assert result.startswith("SECURITY BLOCK:")


# --------------------------------------------------
# 5. BLOCK NON-SELECT QUERY FORMS
# --------------------------------------------------

@pytest.mark.parametrize(
    "query",
    [
        "WITH FleetData AS (SELECT 1 AS id) SELECT * FROM FleetData",
        "",
        "   ",
        "EXECUTE sp_help",
    ],
)
def test_non_select_queries_are_blocked(query):
    """Only queries beginning with SELECT are permitted by this validator."""
    result = validate_select(query)

    assert result is not None
    assert result.startswith("SECURITY BLOCK:")


# --------------------------------------------------
# 6. BLOCK DANGEROUS SQL SERVER FEATURES
# --------------------------------------------------

@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM OPENROWSET('SQLNCLI', 'server'; 'user'; 'pass', "
        "'SELECT 1')",
        "SELECT 1 WAITFOR DELAY '00:00:05'",
        "SELECT xp_cmdshell('whoami')",
        "SELECT * INTO new_table FROM existing_table",
    ],
)
def test_dangerous_sql_server_features_are_blocked(query):
    """SQL Server features outside the permitted policy must be rejected."""
    result = validate_select(query)

    assert result is not None
    assert result.startswith("SECURITY BLOCK:")

# --------------------------------------------------
# 7. TOOL-LEVEL SECURITY TESTS
# --------------------------------------------------

from unittest.mock import patch

from src.agent_tools import query_telemetry_db


def test_tool_rejects_write_query_before_database_connection():
    """Rejected SQL must not open a database connection."""

    with patch("src.agent_tools._telemetry_engine") as mock_engine:
        result = query_telemetry_db.invoke({
            "sql_query": "DELETE FROM FDE_VIEWS.VW_ACTIVE_FLEET"
        })

        assert isinstance(result, str)
        assert result.startswith("SECURITY BLOCK:")
        mock_engine.assert_not_called()


def test_tool_executes_read_only_aggregate_query():
    """A valid aggregate query should return its database result."""

    expected = 32065

    with patch("src.agent_tools._telemetry_engine") as mock_engine:
        mock_connection = mock_engine.return_value.connect.return_value.__enter__.return_value
        mock_cursor = mock_connection.execute.return_value

        mock_cursor.keys.return_value = ["TotalRecords"]
        mock_cursor.fetchmany.return_value = [(expected,)]

        result = query_telemetry_db.invoke({
            "sql_query": (
                "SELECT COUNT(*) AS TotalRecords "
                "FROM FDE_VIEWS.VW_ACTIVE_FLEET"
            )
        })

        assert "TotalRecords" in result
        assert "32065" in result
        mock_engine.assert_called_once()

def test_rejected_query_never_attempts_database_connection():
    """A rejected query must not initialize or access the database engine."""

    with patch(
        "src.agent_tools._telemetry_engine",
        side_effect=AssertionError(
            "Database engine must not be accessed for rejected SQL"
        ),
    ):
        result = query_telemetry_db.invoke({
            "sql_query": (
                "DELETE FROM FDE_VIEWS.VW_ACTIVE_FLEET"
            )
        })

    assert result.startswith("SECURITY BLOCK:")

# --------------------------------------------------
# 8. SQL STRING-LITERAL REGRESSION TESTS
# --------------------------------------------------

@pytest.mark.parametrize(
    "query",
    [
        "SELECT 'DELETE' AS Example",
        "SELECT 'INSERT INTO a table' AS Example",
        "SELECT 'UPDATE records' AS Example",
        "SELECT 'DROP TABLE example' AS Example",
        """
        SELECT
            CASE
                WHEN Risk_Classification = 'High Risk'
                THEN 'DELETE'
                ELSE 'KEEP'
            END AS Example
        FROM FDE_VIEWS.VW_ACTIVE_FLEET
        """,
    ],
)
def test_forbidden_keywords_inside_string_literals_are_allowed(query):
    """Forbidden words inside string literals are not SQL operations."""
    assert validate_select(query) is None


def test_actual_delete_statement_remains_blocked():
    """A real DELETE operation must still be rejected."""
    result = validate_select(
        "DELETE FROM FDE_VIEWS.VW_ACTIVE_FLEET"
    )

    assert result is not None
    assert result.startswith("SECURITY BLOCK:")


def test_cte_remains_blocked():
    """CTEs remain unsupported under the current conservative policy."""
    result = validate_select(
        "WITH FleetData AS (SELECT 1 AS id) "
        "SELECT * FROM FleetData"
    )

    assert result is not None
    assert result.startswith("SECURITY BLOCK:")