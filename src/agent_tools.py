import os
import re
import urllib.parse
import requests
from functools import lru_cache
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import time
from langchain_core.tools import tool
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore

# ENVIRONMENT & DYNAMIC INDEX ATTACHMENT

script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent

load_dotenv(dotenv_path=project_root / ".env")

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
EMBEDDINGS_MODEL_SETTING = os.getenv("Embeddings_model", "LOCAL").strip().upper()

db_host = os.getenv("SQL_SERVER_HOST", "localhost")
db_port = os.getenv("SQL_SERVER_PORT", "1433")
db_user = os.getenv("SQL_AGENT_USER", "USR_FDE_RO")
db_password = os.getenv("SQL_AGENT_PASSWORD", "")


@lru_cache(maxsize=1)
def get_cached_huggingface_embeddings(model_name: str):
    """
    Load the embedding model from the local Hugging Face cache when available.
    Cache the initialized embedding object for the lifetime of this process.
    """
    from langchain_huggingface import HuggingFaceEmbeddings

    cache_root = Path.home() / ".cache" / "huggingface" / "hub"
    model_cache = cache_root / "models--BAAI--bge-m3" / "snapshots"
    local_snapshot = model_cache / "5617a9f61b028005a4858fdac845db406aefb181"

    if (
        model_name == "BAAI/bge-m3"
        and (local_snapshot / "config.json").is_file()
        and (local_snapshot / "pytorch_model.bin").is_file()
    ):
        model_path = str(local_snapshot)
        local_only = True
        print("📦 Loading BGE-M3 from the local Hugging Face snapshot...")
    else:
        model_path = model_name
        local_only = False
        print(f"🌐 Loading embedding model: {model_name}")

    return HuggingFaceEmbeddings(
        model_name=model_path,
        model_kwargs={
            "device": "cpu",
            "local_files_only": local_only,
        },
        encode_kwargs={"normalize_embeddings": True},
    )


@lru_cache(maxsize=1)
def get_cached_sop_retriever():
    """
    Initialize the embedding model and Pinecone retriever only when
    SOP retrieval is first requested. Reuse them for subsequent calls.
    """
    if not PINECONE_API_KEY:
        return None

    if EMBEDDINGS_MODEL_SETTING == "OPENAI":
        print("🤖 Mode: Connecting to Cloud OpenAI Index (1536 Dim Space)...")
        embeddings = OpenAIEmbeddings()
        index_name = "fde-sop-index-openai"
    else:
        local_model_target = os.getenv("Local_Embedding_Model", "BAAI/bge-m3").strip()

        print(
            f"🤗 Mode: Connecting to Local Fallback "
            f"[{local_model_target}] Index (1024 Dim Space)..."
        )
        embeddings = get_cached_huggingface_embeddings(local_model_target)
        index_name = "fde-sop-index-local"

    vector_store = PineconeVectorStore(
        index_name=index_name,
        embedding=embeddings,
    )

    return vector_store.as_retriever(search_kwargs={"k": 2})


# SQL GUARDRAILS
# The database login is already read-only. This check is a second lock in front of it.

_FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|GRANT|REVOKE|DENY|EXEC|EXECUTE|"
    r"INTO|OPENROWSET|OPENQUERY|OPENDATASOURCE|BULK|WAITFOR|SHUTDOWN)\b|\bxp_\w+|\bsp_\w+",
    re.IGNORECASE,
)


def _mask_sql_strings(sql: str) -> tuple[str, bool, bool]:
    """
    Replace SQL single-quoted string literals with spaces.

    Returns:
        masked_sql: SQL with string literal contents masked.
        has_comment: Whether a SQL comment appears outside a string.
        unterminated_string: Whether a string literal is unclosed.

    Handles escaped SQL single quotes ('').
    """
    masked = []
    i = 0
    in_string = False
    has_comment = False

    while i < len(sql):
        char = sql[i]

        if in_string:
            if char == "'":
                # SQL escapes a single quote by doubling it.
                if i + 1 < len(sql) and sql[i + 1] == "'":
                    masked.extend([" ", " "])
                    i += 2
                    continue

                in_string = False

            masked.append(" ")
            i += 1
            continue

        # Outside strings, SQL comments remain prohibited.
        if sql.startswith("--", i) or sql.startswith("/*", i):
            has_comment = True

        if char == "'":
            in_string = True
            masked.append(" ")
        else:
            masked.append(char)

        i += 1

    return "".join(masked), has_comment, in_string


def validate_select(sql_query: str):
    """
    Reject statements outside the application's restricted SELECT policy.

    This is an application-level guardrail, not a complete SQL parser.
    The database account must independently enforce read-only permissions.
    """
    if not isinstance(sql_query, str) or not sql_query.strip():
        return "SECURITY BLOCK: A non-empty SQL query is required."

    masked, has_comment, unterminated_string = _mask_sql_strings(sql_query)

    if unterminated_string:
        return "SECURITY BLOCK: Unterminated SQL string literal."

    if has_comment:
        return "SECURITY BLOCK: SQL comments are not allowed."

    # Check the statement type while ignoring quoted string contents.
    stripped = masked.strip()

    if not stripped.upper().startswith("SELECT"):
        return "SECURITY BLOCK: Only SELECT operations are authorized on this view."

    # Permit one optional trailing semicolon, but reject multiple statements.
    stripped = stripped.rstrip().removesuffix(";").rstrip()

    if ";" in stripped:
        return "SECURITY BLOCK: Only a single SELECT statement is allowed."

    # Scan actual SQL syntax, not the contents of string literals.
    if _FORBIDDEN_SQL.search(stripped):
        return (
            "SECURITY BLOCK: This statement uses a keyword "
            "that is not authorized on this view."
        )

    return None


@lru_cache(maxsize=1)
def _telemetry_engine():
    """One shared connection pool for all telemetry queries (was: a new engine on every call)."""
    connection_string = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={db_host},{db_port};"
        f"DATABASE=master;"
        f"UID={db_user};"
        f"PWD={db_password};"
        f"Encrypt=no;"
        f"TrustServerCertificate=yes;"
    )
    params = urllib.parse.quote_plus(connection_string)
    return create_engine(f"mssql+pyodbc:///?odbc_connect={params}", pool_pre_ping=True)


# CORE FDE AGENT TOOLS


@tool
def query_telemetry_db(sql_query: str) -> str:
    """
    Executes a read-only SQL query against FDE_VIEWS.VW_ACTIVE_FLEET.

    Available columns:
    Timestamp, Latitude, Longitude, Current_Temperature_C,
    Cargo_Condition_Code, Risk_Classification, Delay_Probability,
    Port_Congestion_Level, Route_Risk_Index.

    Guidelines:
    - Use standard SQL Server T-SQL.
    - Prefer COUNT, AVG, MIN, MAX, and GROUP BY for analytical questions.
    - Use a single aggregate query when it can answer the question.
    - Group continuous numeric values into meaningful bands when necessary.
    - Do not group by raw continuous measurements when that would produce thousands of nearly unique groups.
    - Return only the columns needed to answer the user's question.
    - Do not invent columns or assume that telemetry rows are unique shipments.
    - Results may be truncated; if a truncation warning appears, do not describe the displayed rows as a complete result.
    - Only read-only SELECT queries are permitted.

    """
    blocked = validate_select(sql_query)
    if blocked:
        return blocked

    try:
        with _telemetry_engine().connect() as conn:
            cursor = conn.execute(text(sql_query))
            columns = list(cursor.keys())

            # Fetch one extra row to detect truncation.
            MAX_RESULT_ROWS = 100
            rows = cursor.fetchmany(MAX_RESULT_ROWS + 1)

            if not rows:
                return "No records matched the query criteria."

            truncated = len(rows) > MAX_RESULT_ROWS
            rows = rows[:MAX_RESULT_ROWS]

            formatted_output = f"COLUMNS: {', '.join(columns)}\n"

            for row in rows:
                formatted_output += str(tuple(row)) + "\n"

            if truncated:
                formatted_output += (
                    f"\nWARNING: Results truncated to {MAX_RESULT_ROWS} rows. "
                    "The full result contains additional rows. "
                    "Do not treat these displayed rows as a complete dataset."
                )

            # Always return the formatted output, whether truncated or not.
            return formatted_output

    except Exception as e:
        return f"Database Error: {str(e)}"


@tool
def fetch_corridor_conditions(latitude: float, longitude: float) -> str:
    """
    Fetches real-time weather and corridor conditions from a live REST API for given GPS coordinates.
    Provides temperature, wind speed, and computed corridor congestion index.
    """
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&current_weather=true"
        response = requests.get(url, timeout=6)
        response.raise_for_status()

        payload = response.json().get("current_weather", {})
        temp = payload.get("temperature", "N/A")
        wind = payload.get("windspeed", 0.0)

        congestion_index = 8.5 if wind > 10.0 else 2.5
        status_note = "High Transit Disruption" if wind > 10.0 else "Corridor Normal"

        return (
            f"--- LIVE CORRIDOR TELEMETRY ---\n"
            f"Target GPS: {latitude}, {longitude}\n"
            f"External Temp: {temp}°C | Wind Speed: {wind} km/h\n"
            f"Corridor Risk: {status_note} (Congestion Index: {congestion_index}/10)\n"
            f"-------------------------------"
        )
    except Exception as e:
        return f"Corridor API Communication Failure: {str(e)}"


@tool
def search_compliance_sop(query: str) -> str:
    """
    Searches enterprise Standard Operating Procedures (SOPs) indexed in Pinecone.
    Use this to retrieve regulatory thresholds, cold-chain breach mitigations,
    and rerouting rules.
    """
    total_start = time.perf_counter()

    try:
        init_start = time.perf_counter()
        retriever = get_cached_sop_retriever()
        init_elapsed = time.perf_counter() - init_start

        retrieval_start = time.perf_counter()
        matched_docs = retriever.invoke(query)
        retrieval_elapsed = time.perf_counter() - retrieval_start

        if not matched_docs:
            result = "No matching compliance clauses found."
        else:
            formatted_context = "\n\n".join(
                [
                    f"[Source: {doc.metadata.get('source_file', 'SOP')} | "
                    f"Format: {doc.metadata.get('file_format', 'RAW')}]\n"
                    f"{doc.page_content}"
                    for doc in matched_docs
                ]
            )
            result = (
                f"--- COMPLIANCE SOP CONTEXT ---\n"
                f"{formatted_context}\n"
                f"------------------------------"
            )

        total_elapsed = time.perf_counter() - total_start

        print(
            f"[PERF] SOP tool: {total_elapsed:.3f}s | "
            f"Retriever initialization/access: {init_elapsed:.3f}s | "
            f"Search: {retrieval_elapsed:.3f}s | "
            f"Documents: {len(matched_docs)}",
            flush=True,
        )

        return result

    except Exception as e:
        print(
            f"[PERF] SOP tool failed after "
            f"{time.perf_counter() - total_start:.3f}s",
            flush=True,
        )
        return f"Vector Store Retrieval Error: {str(e)}"


# LOCAL VERIFICATION

if __name__ == "__main__":
    print("\n--- Testing Tool 1: SQL Telemetry View ---")
    print(
        query_telemetry_db.invoke(
            "SELECT TOP 2 Latitude, Longitude, Current_Temperature_C FROM FDE_VIEWS.VW_ACTIVE_FLEET"
        )
    )

    print("\n--- Testing Tool 2: Live Corridor API ---")
    print(fetch_corridor_conditions.invoke({"latitude": 33.77, "longitude": -118.19}))

    print("\n--- Testing Tool 3: Pinecone Vector Retrieval ---")
    print(
        search_compliance_sop.invoke(
            "What are the temperature rules for fresh perishables?"
        )
    )
