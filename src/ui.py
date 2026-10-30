from __future__ import annotations
import asyncio
import queue
import threading
import hmac
import json
import logging
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import ToolMessage
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.pool import NullPool

# ---------------------------------------------------------------------------
# Paths, environment and logging
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Explicit path avoids relying on the caller's current working directory.
load_dotenv(PROJECT_ROOT / ".env", override=False)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("nivara.api")

from src.orchestrator import AGENT_LLM_SETTING, build_turn, fde_agent  # noqa: E402

# The tables/views currently live in master on this SQL Server instance.
DB_HOST = os.getenv("SQL_SERVER_HOST", "127.0.0.1")
DB_PORT = os.getenv("SQL_SERVER_PORT", "11433")
DB_NAME = os.getenv("SQL_SERVER_DATABASE", "master")
DB_USER = os.getenv("SQL_AGENT_USER", "USR_FDE_RO")
DB_PASSWORD = os.getenv("SQL_AGENT_PASSWORD")
DB_CONNECT_TIMEOUT = max(3, int(os.getenv("SQL_CONNECT_TIMEOUT", "8")))
DB_RETRIES = max(1, min(3, int(os.getenv("SQL_RETRIES", "2"))))

VIEW = "FDE_VIEWS.VW_ACTIVE_FLEET"
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _make_engine(user: str, password: str, *, pooled: bool = True):
    """Build an ODBC engine using the configured endpoint and database."""
    if not user or not password:
        raise RuntimeError("SQL credentials are not configured in the environment.")

    odbc = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER=tcp:{DB_HOST},{DB_PORT};"
        f"DATABASE={DB_NAME};"
        f"UID={user};"
        f"PWD={password};"
        "Encrypt=no;"
        "TrustServerCertificate=yes;"
        f"Connection Timeout={DB_CONNECT_TIMEOUT};"
    )
    url = "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(odbc)
    if pooled:
        return create_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=90,
            pool_timeout=10,
            pool_size=2,
            max_overflow=2,
            connect_args={"timeout": DB_CONNECT_TIMEOUT},
        )
    return create_engine(
        url,
        poolclass=NullPool,
        connect_args={"timeout": DB_CONNECT_TIMEOUT},
    )


# Do not prevent the API from starting if DB credentials have not been set.
# Database-dependent endpoints return a controlled error in that case.
try:
    log_engine = _make_engine(DB_USER, DB_PASSWORD, pooled=True)
except Exception as exc:  # configuration error; defer failure to DB endpoints
    log_engine = None
    logger.error("Database engine is not configured: %s", exc)


def _require_log_engine():
    if log_engine is None:
        raise RuntimeError(
            "SQL connection is not configured; check SQL_SERVER_* and SQL_AGENT_* settings."
        )
    return log_engine


def _is_connection_error(exc: Exception) -> bool:
    return isinstance(exc, OperationalError) or bool(
        getattr(exc, "connection_invalidated", False)
    )


def write_audit_log(
    session_id: str, node_name: str, tool_name: str, content: str
) -> None:
    """Write an audit row; transient DB errors are retried without failing chat."""
    engine = _require_log_engine()
    params = {
        "session_id": session_id[:128],
        "node_name": node_name[:128],
        "tool_name": tool_name[:256],
        # Prevent an unexpectedly huge tool response from bloating the audit log.
        "content": content[:100_000] if content else "",
    }
    for attempt in range(1, DB_RETRIES + 1):
        try:
            # begin() commits on success and rolls back on failure.
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO FDE_VIEWS.AgentAuditLog "
                        "(SessionID, NodeExecuted, ToolName, Content) "
                        "VALUES (:session_id, :node_name, :tool_name, :content)"
                    ),
                    params,
                )
            return
        except Exception as exc:  # audit failure must not break a chat turn
            if attempt < DB_RETRIES and _is_connection_error(exc):
                logger.warning(
                    "Audit DB connection failed (attempt %s/%s); retrying.",
                    attempt,
                    DB_RETRIES,
                )
                try:
                    engine.dispose()
                except Exception:
                    pass
                time.sleep(0.35 * attempt)
                continue
            logger.warning(
                "Audit write failed (%s): %s", type(exc).__name__, str(exc)[:300]
            )
            return


# ---------------------------------------------------------------------------
# Background audit queue
# ---------------------------------------------------------------------------
AUDIT_QUEUE_MAX_SIZE = 5000
audit_queue: queue.Queue[tuple[str, str, str, str] | None] = queue.Queue(
    maxsize=AUDIT_QUEUE_MAX_SIZE
)


def _audit_worker() -> None:
    """Write queued audit records without blocking chat generation."""
    while True:
        record = audit_queue.get()

        try:
            if record is None:
                return

            session_id, node_name, tool_name, content = record
            write_audit_log(session_id, node_name, tool_name, content)

        except Exception:
            logger.exception("Unexpected error in background audit worker.")
        finally:
            audit_queue.task_done()


def enqueue_audit_log(
    session_id: str,
    node_name: str,
    tool_name: str,
    content: str,
) -> None:
    """Queue an audit record without waiting for the database."""
    record = (
        session_id,
        node_name,
        tool_name,
        content,
    )

    try:
        audit_queue.put_nowait(record)
    except queue.Full:
        # Explicitly report the loss instead of silently dropping the record.
        logger.error(
            "Audit queue full; audit record could not be queued "
            "(session=%s, node=%s, tool=%s).",
            session_id[:64],
            node_name[:128],
            tool_name[:128],
        )


audit_thread = threading.Thread(
    target=_audit_worker,
    name="audit-writer",
    daemon=True,
)
audit_thread.start()


# ---------------------------------------------------------------------------
# API models and application
# ---------------------------------------------------------------------------
class ChatIn(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)
    message: str = Field(min_length=1, max_length=4000)


class AuditIn(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm up the SOP retriever without making startup depend on it."""
    logger.info("Starting Nivara API...")

    async def warm_sop_retriever():
        try:
            from src.agent_tools import get_cached_sop_retriever

            start = time.perf_counter()
            await asyncio.to_thread(get_cached_sop_retriever)
            elapsed = time.perf_counter() - start

            logger.info(
                "SOP retriever ready in %.2f seconds.",
                elapsed,
            )
        except Exception:
            logger.exception(
                "SOP retriever warm-up failed; " "the API will continue starting."
            )

    warmup_task = asyncio.create_task(warm_sop_retriever())

    try:
        yield
    finally:
        if not warmup_task.done():
            warmup_task.cancel()
            try:
                await warmup_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="Nivara API", lifespan=lifespan)

_default_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
]
_extra_origins = [
    x.strip().rstrip("/") for x in os.getenv("CORS_ORIGINS", "").split(",") if x.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys(_default_origins + _extra_origins)),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


def _line(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str) + "\n"


def _as_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content)


def _chat_events(session_id: str, message: str):
    try:
        payload, config = build_turn(session_id, message)
        final = ""
        for event in fde_agent.stream(payload, config=config, stream_mode="updates"):
            for node, state in event.items():
                if node == "reasoner":
                    messages = state.get("messages", [])
                    if not messages:
                        continue
                    last = messages[-1]
                    for call in getattr(last, "tool_calls", None) or []:
                        enqueue_audit_log(
                            session_id,
                            "reasoner",
                            str(call.get("name", "unknown")),
                            json.dumps(
                                call.get("args", {}), ensure_ascii=False, default=str
                            ),
                        )
                        yield _line(
                            {
                                "type": "tool_input",
                                "name": call.get("name", "unknown"),
                                "args": call.get("args", {}),
                            }
                        )
                    body = _as_text(getattr(last, "content", ""))
                    if body:
                        final = body
                        enqueue_audit_log(
                            session_id, "reasoner_final", "LLM Text Synthesis", body
                        )
                elif node == "tools":
                    for msg in state.get("messages", []):
                        if isinstance(msg, ToolMessage):
                            output = _as_text(msg.content)
                            enqueue_audit_log(
                                session_id, "tools", msg.name or "unknown", output
                            )
                            yield _line(
                                {
                                    "type": "tool_output",
                                    "name": msg.name,
                                    "content": output,
                                }
                            )
        if final:
            yield _line({"type": "final", "content": final})
        else:
            yield _line(
                {
                    "type": "error",
                    "message": "The agent finished without producing an answer.",
                }
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Chat request failed")
        # Avoid returning stack traces or secrets to the browser.
        yield _line(
            {
                "type": "error",
                "message": f"The request failed ({type(exc).__name__}). Check the server logs.",
            }
        )


@app.get("/api/health")
def health():
    return {"status": "ok", "llm": AGENT_LLM_SETTING}


@app.post("/api/chat")
def chat(body: ChatIn):
    if not SESSION_RE.fullmatch(body.session_id):
        raise HTTPException(status_code=400, detail="Invalid session id.")
    return StreamingResponse(
        _chat_events(body.session_id, body.message),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Audit trail (admin-only read)
# ---------------------------------------------------------------------------
_FAILED_LOGINS: dict[str, list[float]] = {}


def _throttled(ip: str) -> bool:
    now = time.time()
    hits = [stamp for stamp in _FAILED_LOGINS.get(ip, []) if now - stamp < 60]
    _FAILED_LOGINS[ip] = hits
    return len(hits) >= 5


@app.post("/api/audit")
def audit(body: AuditIn, request: Request):
    ip = request.client.host if request.client else "unknown"
    if _throttled(ip):
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Wait a minute and try again.",
        )

    admin_user = os.getenv("SQL_ADMIN_USER")
    admin_password = os.getenv("SQL_ADMIN_PASSWORD")
    if not admin_user or not admin_password:
        raise HTTPException(
            status_code=503, detail="Admin credentials are not configured."
        )

    username_ok = hmac.compare_digest(body.username.encode(), admin_user.encode())
    password_ok = hmac.compare_digest(body.password.encode(), admin_password.encode())
    if not (username_ok and password_ok):
        _FAILED_LOGINS.setdefault(ip, []).append(time.time())
        raise HTTPException(
            status_code=401, detail="Invalid administrator credentials."
        )

    admin_engine = None
    try:
        admin_engine = _make_engine(admin_user, admin_password, pooled=False)
        with admin_engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT TOP 500 LogID, Timestamp, SessionID, NodeExecuted, ToolName, Content "
                        "FROM FDE_VIEWS.AgentAuditLog ORDER BY Timestamp DESC"
                    )
                )
                .mappings()
                .all()
            )
        # Successful authentication clears this IP's recent failures.
        _FAILED_LOGINS.pop(ip, None)
        return {
            "rows": [
                {
                    key: (str(value) if value is not None else None)
                    for key, value in row.items()
                }
                for row in rows
            ]
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Admin audit query failed")
        raise HTTPException(
            status_code=500, detail=f"Database query failed ({type(exc).__name__})."
        ) from exc
    finally:
        if admin_engine is not None:
            admin_engine.dispose()


# ---------------------------------------------------------------------------
# Chart statistics (read-only aggregates over the semantic view)
# ---------------------------------------------------------------------------
_STATS_CACHE: dict[str, Any] = {"timestamp": 0.0, "value": None}
TS_EXPR = "TRY_CONVERT(datetime2, [Timestamp])"


def _query_rows(sql: str, **params):
    engine = _require_log_engine()
    for attempt in range(1, DB_RETRIES + 1):
        try:
            with engine.connect() as conn:
                return [
                    tuple(row) for row in conn.execute(text(sql), params).fetchall()
                ]
        except Exception as exc:
            if attempt < DB_RETRIES and _is_connection_error(exc):
                logger.warning(
                    "Stats DB connection failed (attempt %s/%s); retrying.",
                    attempt,
                    DB_RETRIES,
                )
                try:
                    engine.dispose()
                except Exception:
                    pass
                time.sleep(0.25 * attempt)
                continue
            raise
    return []


def _histogram(column: str, bins: int = 24):
    # column is only called with fixed internal identifiers below.
    lo, hi, count = _query_rows(
        f"SELECT MIN(TRY_CAST([{column}] AS float)), MAX(TRY_CAST([{column}] AS float)), "
        f"COUNT(TRY_CAST([{column}] AS float)) FROM {VIEW} WHERE TRY_CAST([{column}] AS float) IS NOT NULL"
    )[0]
    if not count or lo is None:
        return None
    lo, hi = float(lo), float(hi)
    if hi == lo:
        hi = lo + 1.0
    width = (hi - lo) / bins
    rows = _query_rows(
        f"SELECT b, COUNT(*) FROM ("
        f"SELECT CASE WHEN TRY_CAST([{column}] AS float) >= :hi THEN :last "
        f"ELSE CAST(FLOOR((TRY_CAST([{column}] AS float) - :lo) / :width) AS int) END AS b "
        f"FROM {VIEW} WHERE TRY_CAST([{column}] AS float) IS NOT NULL"
        f") AS source_rows GROUP BY b",
        lo=lo,
        hi=hi,
        width=width,
        last=bins - 1,
    )
    counts = [0] * bins
    for bucket, amount in rows:
        if bucket is not None and 0 <= int(bucket) < bins:
            counts[int(bucket)] += int(amount)
    return {"min": lo, "max": hi, "bins": counts, "width": width}


def _congestion():
    rows = _query_rows(
        f"SELECT CAST(Port_Congestion_Level AS varchar(60)), "
        f"AVG(TRY_CAST(Delay_Probability AS float)), COUNT(*) FROM {VIEW} "
        "WHERE Port_Congestion_Level IS NOT NULL AND TRY_CAST(Delay_Probability AS float) IS NOT NULL "
        "GROUP BY CAST(Port_Congestion_Level AS varchar(60))"
    )
    if not rows:
        return []

    def as_number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    numeric = all(as_number(row[0]) is not None for row in rows)
    if numeric and len(rows) > 14:
        values = [as_number(row[0]) for row in rows]
        low, high, bins = min(values), max(values), 10
        width = (high - low) / bins or 1.0
        aggregate = [[0.0, 0] for _ in range(bins)]
        for label, average, amount in rows:
            index = min(bins - 1, int((as_number(label) - low) / width))
            aggregate[index][0] += float(average) * int(amount)
            aggregate[index][1] += int(amount)
        return [
            {
                "label": f"{low + i * width:.1f}-{low + (i + 1) * width:.1f}",
                "avg": total / amount,
                "n": amount,
            }
            for i, (total, amount) in enumerate(aggregate)
            if amount
        ]

    rows.sort(
        key=(lambda row: as_number(row[0])) if numeric else (lambda row: str(row[0]))
    )
    return [
        {"label": row[0], "avg": float(row[1]), "n": int(row[2])} for row in rows[:14]
    ]


def _trend():
    span = _query_rows(
        f"SELECT DATEDIFF(day, MIN({TS_EXPR}), MAX({TS_EXPR})) FROM {VIEW} WHERE {TS_EXPR} IS NOT NULL"
    )[0][0]
    if span is None:
        return [], "day"
    grain = "month" if span > 120 else "day"
    length = 7 if grain == "month" else 10
    key = f"LEFT(CONVERT(varchar(30), {TS_EXPR}, 120), {length})"
    rows = _query_rows(
        f"SELECT TOP 180 k, average_delay FROM ("
        f"SELECT {key} AS k, AVG(TRY_CAST(Delay_Probability AS float)) AS average_delay "
        f"FROM {VIEW} WHERE {TS_EXPR} IS NOT NULL AND TRY_CAST(Delay_Probability AS float) IS NOT NULL "
        f"GROUP BY {key}) AS trend_rows ORDER BY k DESC"
    )
    rows.reverse()
    return [{"x": row[0], "y": float(row[1])} for row in rows], grain


@app.get("/api/stats")
def stats():
    now = time.time()
    cached = _STATS_CACHE["value"]
    if cached is not None and now - _STATS_CACHE["timestamp"] < 300:
        return cached

    result: dict[str, Any] = {
        "source": "database",
        "tempUnit": "°C",
        "errors": [],
        "grain": "day",
    }

    def safe_part(name: str, function: Callable[[], Any]) -> None:
        try:
            result[name] = function()
        except Exception as exc:
            result[name] = None
            result["errors"].append(f"{name}: {type(exc).__name__}")
            logger.warning("Stats section '%s' failed: %s", name, exc)

    def totals():
        rows = _query_rows(
            f"SELECT COUNT(*), AVG(TRY_CAST(Delay_Probability AS float)), "
            f"AVG(TRY_CAST(Current_Temperature_C AS float)) FROM {VIEW}"
        )
        total, average_delay, average_temperature = rows[0]
        result["avgDelay"] = float(average_delay) if average_delay is not None else None
        result["avgTemp"] = (
            float(average_temperature) if average_temperature is not None else None
        )
        return int(total)

    def trend_part():
        points, grain = _trend()
        result["grain"] = grain
        return points

    safe_part("total", totals)
    if result.get("total") is None:
        raise HTTPException(
            status_code=500,
            detail="Could not read the fleet view. Check database settings and server logs.",
        )

    safe_part(
        "risk",
        lambda: [
            {"label": row[0], "n": int(row[1])}
            for row in _query_rows(
                f"SELECT TOP 10 CAST(Risk_Classification AS varchar(60)), COUNT(*) FROM {VIEW} "
                "WHERE Risk_Classification IS NOT NULL "
                "GROUP BY CAST(Risk_Classification AS varchar(60)) ORDER BY COUNT(*) DESC"
            )
        ],
    )
    safe_part("temp", lambda: _histogram("Current_Temperature_C"))
    safe_part("delay", lambda: _histogram("Delay_Probability"))
    safe_part("congestion", _congestion)
    safe_part("daily", trend_part)
    safe_part(
        "scatter",
        lambda: [
            [float(row[0]), float(row[1])]
            for row in _query_rows(
                f"SELECT TOP 400 TRY_CAST(Route_Risk_Index AS float), TRY_CAST(Delay_Probability AS float) "
                f"FROM {VIEW} WHERE TRY_CAST(Route_Risk_Index AS float) IS NOT NULL "
                "AND TRY_CAST(Delay_Probability AS float) IS NOT NULL ORDER BY NEWID()"
            )
        ],
    )

    _STATS_CACHE.update(timestamp=now, value=result)
    return result


# ---------------------------------------------------------------------------
# Temporary SSH tunnel diagnostic
# ---------------------------------------------------------------------------
import socket


@app.get("/api/debug-connection")
def debug_connection():
    try:
        with socket.create_connection(("127.0.0.1", 11433), timeout=5):
            return {"ssh_tunnel": "CONNECTED"}
    except OSError:
        return {"ssh_tunnel": "UNREACHABLE"}


# ---------------------------------------------------------------------------
# Frontend (mount last so it does not shadow API routes)
# ---------------------------------------------------------------------------
WEB_DIR = PROJECT_ROOT / "web"
if (WEB_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
else:

    @app.get("/", response_class=PlainTextResponse)
    def missing_frontend():
        return f"Nivara API is running, but {WEB_DIR / 'index.html'} was not found. Put index.html in the web/ folder at the project root."


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.ui:app",
        host=os.getenv("NIVARA_HOST", "127.0.0.1"),
        port=int(os.getenv("NIVARA_PORT", "8000")),
    )
