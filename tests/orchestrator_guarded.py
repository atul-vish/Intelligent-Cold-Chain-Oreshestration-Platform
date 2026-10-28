import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import tools_condition
from langgraph.checkpoint.memory import MemorySaver

# ==========================================
# 1. SETUP & PATH RESOLUTION
# ==========================================
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parents[0]

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.agent_tools import (
    query_telemetry_db,
    get_fleet_overview,
    get_temperature_distribution,
    get_risk_analysis,
    get_data_quality_report,
    get_historical_trends,
    fetch_corridor_conditions,
    search_compliance_sop,
)

load_dotenv(project_root / ".env")


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


# ==========================================
# 2. FACTORY INITIALIZATION: AGENT REASONER LLM
# ==========================================

AGENT_LLM_SETTING = os.getenv("Agent_llm", "OLLAMA").strip().upper()

if AGENT_LLM_SETTING == "OPENAI":
    print("🤖 Brain Mode: Utilizing Cloud OpenAI Reasoner (gpt-4o)...")
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(model="gpt-4o", temperature=0)

elif AGENT_LLM_SETTING == "DEEPSEEK":
    print(
        "🐳 Brain Mode: Utilizing Flagship DeepSeek Cloud Reasoner (deepseek-v4-pro)..."
    )
    from langchain_openai import ChatOpenAI

    # Fully updated to match 2026 DeepSeek API parameters and endpoint contracts
    llm = ChatOpenAI(
        model="deepseek-flash",  # deepseek-v4-flash, deepseek-v4-pro
        temperature=0,
        openai_api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",  # Fixed connection string url endpoint
        max_tokens=2048,  # Gives the deep reasoner plenty of output runway
        # extra_body={
        #     "thinking": {"type": "enabled"},              # Activates DeepSeek Deep-Thinking mode
        #     "reasoning_effort": "high"                     # Drives maximal reasoning depth for logic maps
        # }
    )

else:  # FALLBACK / DEFAULT RUNNER MODE
    print(
        "🤗 Brain Mode: Local Fallback Activated. Binding Local Ollama (qwen2.5:7b)..."
    )
    from langchain_community.chat_models import ChatOllama

    llm = ChatOllama(model="qwen2.5:7b", temperature=0, num_predict=1024)

# ==========================================
# 2.1 INTENT-AWARE TOOL ROUTING
# ==========================================

import re

TOOL_REGISTRY = {
    "telemetry": query_telemetry_db,
    "fleet_overview": get_fleet_overview,
    "temperature_distribution": get_temperature_distribution,
    "risk_analysis": get_risk_analysis,
    "data_quality": get_data_quality_report,
    "historical_trends": get_historical_trends,
    "corridor": fetch_corridor_conditions,
    "sop": search_compliance_sop,
}

# Match decimal coordinates supplied in the user's request.
COORDINATE_PATTERN = re.compile(r"(-?\d{1,2}(?:\.\d+)?)\s*[,/]\s*(-?\d{1,3}(?:\.\d+)?)")

# Examples: shipment SHP123, vehicle TRUCK-102, consignment CN-12345.
IDENTIFIER_PATTERN = re.compile(
    # Require at least one digit so words such as "temperature" are not
    # mistaken for identifiers in phrases like "shipment temperature".
    r"\b(?:shipment|vehicle|truck|consignment)\s*"
    r"(?:id|number|no\.?|#)?\s*[:#-]?\s*"
    r"([A-Z0-9_-]*\d[A-Z0-9_-]{2,})\b",
    re.IGNORECASE,
)

# The currently approved telemetry view contains no verified shipment,
# vehicle, truck, consignment, or device identifier. Keep this False until
# a real, validated mapping is added to the data model.
SHIPMENT_IDENTITY_MAPPING_AVAILABLE = False


def get_latest_user_text(messages) -> str:
    """Return the latest human message from the conversation."""

    for message in reversed(messages):
        if getattr(message, "type", None) == "human":
            content = getattr(message, "content", "")
            if isinstance(content, str):
                return content

    return ""


def classify_request(user_text: str) -> str:
    """
    Classify the user's intent before exposing tools to the LLM.

    Categories:
      policy_only
      hypothetical_incident
      shipment_investigation
      fleet_overview
      corridor_conditions
      general
    """

    text = user_text.lower()

    # Resolve specialized analytics intents before broader fleet matching.
    if any(term in text for term in ("data quality", "data-quality", "missing values", "duplicate timestamps", "invalid coordinates", "data validation")):
        return "data_quality"
    if any(term in text for term in ("temperature distribution", "temperature bands", "temperature buckets", "temperature ranges", "bucket counts")):
        return "temperature_distribution"
    if any(term in text for term in ("historical trend", "historical trends", "trend over time", "year over year", "year-by-year", "monthly trend", "annual trend", "by month", "by year")):
        return "historical_trends"
    if any(term in text for term in ("risk analysis", "risk breakdown", "risk distribution", "risk classification breakdown", "risk classes")):
        return "risk_analysis"

    # Hypothetical scenarios must not be treated as verified database incidents.
    hypothetical_markers = (
        "hypothetical",
        "hypothetically",
        "suppose",
        "assume that",
        "imagine a shipment",
        "if a shipment",
        "if the temperature",
        "scenario:",
        "what would happen if",
    )

    has_temperature_scenario = any(term in text for term in hypothetical_markers) or (
        re.search(r"\d+(?:\.\d+)?\s*°?\s*(?:c|celsius)\b", text)
        and any(
            term in text
            for term in (
                "dispatcher",
                "what actions",
                "what should",
                "what must",
                "temperature reading",
            )
        )
    )

    if has_temperature_scenario:
        return "hypothetical_incident"

    # General questions about procedures should use the approved SOP source.
    policy_terms = (
        "sop",
        "standard operating procedure",
        "temperature rules",
        "temperature threshold",
        "temperature limit",
        "compliance policy",
        "documentation requirements",
        "escalation procedure",
        "corrective action",
    )

    asks_for_policy = any(term in text for term in policy_terms)

    # A question about an actual incident is not automatically a policy question.
    asks_for_live_investigation = any(
        term in text
        for term in (
            "investigate shipment",
            "investigate vehicle",
            "check shipment",
            "check vehicle",
            "current reading",
            "latest reading",
            "why is shipment",
            "shipment at risk",
            "temperature excursion",
            "actual incident",
        )
    )

    if asks_for_policy and not asks_for_live_investigation:
        return "policy_only"

    # Broad operational questions covering multiple records.
    fleet_terms = (
        "all shipments",
        "which shipments",
        "fleet overview",
        "overview of fleet",
        "fleet status",
        "fleet summary",
        "show me the fleet",
        "fleet temperature",
        "temperature and risk",
        "temperature distribution",
        "risk overview",
        "fleet-wide",
        "temperature excursions across",
        "high-risk shipments",
    )

    if any(term in text for term in fleet_terms):
        return "fleet_overview"

    # Corridor/weather analysis requires relevant coordinates.
    corridor_terms = (
        "corridor conditions",
        "weather conditions",
        "weather on this route",
        "route disruption",
        "environmental conditions",
    )

    if any(term in text for term in corridor_terms):
        return "corridor_conditions"

    # Shipment-specific questions with an explicit identifier must be
    # stopped before SQL when the telemetry schema cannot map that identity.
    shipment_operational_terms = (
        "shipment",
        "vehicle",
        "truck",
        "consignment",
        "temperature",
        "telemetry",
        "reading",
        "risk",
        "delay",
        "status",
        "location",
        "current",
        "latest",
        "investigate",
        "check",
        "track",
    )
    if IDENTIFIER_PATTERN.search(user_text) and any(
        term in text for term in shipment_operational_terms
    ):
        return "shipment_investigation"

    # Shipment-specific investigation without an explicit identifier must
    # never fall back to querying arbitrary fleet records.
    if any(
        term in text
        for term in (
            "investigate shipment",
            "investigate vehicle",
            "check shipment",
            "check vehicle",
            "current reading",
            "latest reading",
            "why is shipment",
            "shipment at risk",
            "temperature excursion",
            "actual incident",
            "current temperature of shipment",
            "latest temperature of shipment",
            "track shipment",
        )
    ):
        return "shipment_investigation"

    return "general"


def get_tools_for_intent(intent: str, user_text: str):
    """Return only the tools permitted for this request."""

    if intent in ("policy_only", "hypothetical_incident"):
        return [TOOL_REGISTRY["sop"]]

    if intent == "shipment_investigation":
        # Fail closed: without a verified identity mapping, do not expose
        # telemetry, SOP, or corridor tools for a shipment-specific request.
        if not SHIPMENT_IDENTITY_MAPPING_AVAILABLE:
            return []

        selected = [
            TOOL_REGISTRY["telemetry"],
            TOOL_REGISTRY["sop"],
        ]

        # Corridor data is allowed only when coordinates are supplied.
        if COORDINATE_PATTERN.search(user_text):
            selected.append(TOOL_REGISTRY["corridor"])

        return selected

    if intent == "data_quality":
        return [TOOL_REGISTRY["data_quality"]]

    if intent == "temperature_distribution":
        return [TOOL_REGISTRY["temperature_distribution"]]

    if intent == "risk_analysis":
        return [TOOL_REGISTRY["risk_analysis"]]

    if intent == "historical_trends":
        return [TOOL_REGISTRY["historical_trends"]]

    if intent == "fleet_overview":
        # SOP retrieval is useful when the user explicitly asks for policy,
        # thresholds, breach handling, or compliance interpretation. Avoid an
        # extra retrieval call for a purely descriptive statistical overview.
        policy_context_terms = (
            "sop", "threshold", "approved range", "compliance", "breach",
            "escalation", "temperature rule", "fresh perishables",
            "mitigation", "corrective action",
        )
        selected = [TOOL_REGISTRY["fleet_overview"]]
        risk_terms = ("risk", "risk classification", "risk breakdown", "risk distribution")
        if any(term in user_text.lower() for term in risk_terms):
            selected.append(TOOL_REGISTRY["risk_analysis"])
        if any(term in user_text.lower() for term in policy_context_terms):
            selected.append(TOOL_REGISTRY["sop"])
        return selected

    if intent == "corridor_conditions":
        if COORDINATE_PATTERN.search(user_text):
            return [TOOL_REGISTRY["corridor"]]

        # Without coordinates, ask the user to provide a location.
        return []

    # No operational tools for unrelated questions.
    return []


# All tools are registered for lookup, but registration does NOT authorize
# execution. The guarded node below independently checks every tool call.
fde_tools = [
    query_telemetry_db,
    get_fleet_overview,
    get_temperature_distribution,
    get_risk_analysis,
    get_data_quality_report,
    get_historical_trends,
    fetch_corridor_conditions,
    search_compliance_sop,
]
TOOLS_BY_NAME = {tool.name: tool for tool in fde_tools}

llm_with_tools = llm.bind_tools(fde_tools)


# ==========================================
# 3. GRAPH ARCHITECTURE ASSEMBLY
# ==========================================


def build_request_instructions(intent: str, user_text: str) -> str:
    """Add per-request planning constraints without mutating saved chat history."""
    common = (
        "REQUEST-SPECIFIC EXECUTION RULES\n"
        "- The database is Microsoft SQL Server: write T-SQL only. Use TOP (N), "
        "never LIMIT; do not use MEDIAN(); never use GROUP BY ordinal positions "
        "such as GROUP BY 1. Use explicit expressions or aliases supported by SQL Server.\n"
        "- Query only FDE_VIEWS.VW_ACTIVE_FLEET and only its documented columns.\n"
        "- Do not retry a failed query with near-identical SQL. Diagnose the error "
        "from the returned message; if it is a syntax issue, make one corrected attempt.\n"
        "- Never infer shipment identity, cargo type, or operational meaning for "
        "undocumented numeric fields. Clearly state data limitations."
    )

    if intent == "data_quality":
        return common + "\n\nUse only get_data_quality_report for the requested data-quality analysis. Report counts as observed; do not claim that values are clean if the report does not support that conclusion."

    if intent == "temperature_distribution":
        return common + "\n\nUse get_temperature_distribution. Default bands are <0, [0,4], (4,8], >8 degrees C. If the user specifies different numeric boundaries, pass those boundaries explicitly. Explain that temperature bands alone do not establish a compliance breach without verified cargo type and approved range."

    if intent == "risk_analysis":
        return common + "\n\nUse only get_risk_analysis for risk-class counts and aggregate comparisons. Do not infer that the recorded label is caused by any particular feature unless supported by evidence."

    if intent == "historical_trends":
        return common + "\n\nUse get_historical_trends. Choose monthly granularity only when the user requests monthly detail; otherwise use yearly granularity. The archive is historical, not live."

    if intent == "fleet_overview":
        return common + "\n\nUse get_fleet_overview for standard summary statistics. Prefer predefined deterministic analytics tools over writing SQL manually."

    if intent == "policy_only":
        return common + "\n\nUse the SOP retriever as the source of policy. Do not query telemetry unless the user asks for measured data."

    if intent == "hypothetical_incident":
        return common + "\n\nTreat the scenario as hypothetical. Use the SOP source; do not present scenario details as actual database observations."

    if intent == "shipment_investigation":
        return common + "\n\nDo not query arbitrary fleet rows as a substitute for a shipment-specific record. If the verified identity mapping is unavailable, explain the limitation and stop."

    return common


def reasoning_node(state: AgentState):
    messages = state["messages"]

    latest_user_text = get_latest_user_text(messages)
    intent = classify_request(latest_user_text)

    allowed_tools = get_tools_for_intent(
        intent=intent,
        user_text=latest_user_text,
    )

    print(f"[Router] Intent: {intent}")

    # Deterministic fail-closed preflight: do not let the LLM attempt an
    # unfiltered telemetry query for a shipment that cannot be identified.
    if intent == "shipment_investigation" and not SHIPMENT_IDENTITY_MAPPING_AVAILABLE:
        print("[Router] Shipment telemetry blocked: no verified identity mapping.")
        return {
            "messages": [
                AIMessage(
                    content=(
                        "I can’t safely investigate that specific shipment from the "
                        "current telemetry schema. The approved view "
                        "`FDE_VIEWS.VW_ACTIVE_FLEET` does not expose a verified "
                        "shipment, vehicle, truck, consignment, or device identifier, "
                        "so I cannot link its records to the ID you supplied. I have "
                        "not queried unrelated fleet rows.\n\n"
                        "I can still provide fleet-level analysis, or you can add a "
                        "verified shipment-to-telemetry mapping before retrying this "
                        "investigation. The available telemetry is historical "
                        "(latest record: 2024-08-29), not live."
                    )
                )
            ]
        }

    print(
        "[Router] Available tools: "
        + (", ".join(tool.name for tool in allowed_tools) if allowed_tools else "None")
    )

    # Bind only the tools allowed for this specific request.
    request_llm = llm.bind_tools(allowed_tools) if allowed_tools else llm

    # Insert transient planning rules immediately before the latest user turn.
    # They are passed to the model for this invocation only and are not stored
    # in graph history, preventing prompt accumulation across turns.
    request_messages = list(messages)
    user_message_index = next(
        (index for index in range(len(request_messages) - 1, -1, -1)
         if getattr(request_messages[index], "type", None) == "human"),
        len(request_messages),
    )
    request_messages.insert(
        user_message_index,
        SystemMessage(content=build_request_instructions(intent, latest_user_text)),
    )

    response = request_llm.invoke(request_messages)

    return {"messages": [response]}


def guarded_tool_node(state: AgentState):
    """
    Execute only tool calls authorized for the latest user request.

    This is an independent enforcement point: the LLM's tool binding and
    the router's selected tool list are not trusted as the sole authorization
    boundary. Unauthorized calls receive a ToolMessage and are never invoked.
    """
    messages = state.get("messages", [])
    if not messages:
        return {"messages": []}

    latest_message = messages[-1]
    calls = getattr(latest_message, "tool_calls", []) or []
    if not calls:
        return {"messages": []}

    user_text = get_latest_user_text(messages)
    intent = classify_request(user_text)
    permitted_names = {
        tool.name for tool in get_tools_for_intent(intent, user_text)
    }

    # Shipment investigations remain blocked even if a model emits a call
    # despite the preflight response or an unexpected graph state.
    if intent == "shipment_investigation" and not SHIPMENT_IDENTITY_MAPPING_AVAILABLE:
        permitted_names = set()

    results = []
    for call in calls:
        tool_name = call.get("name", "")
        tool_call_id = call.get("id") or f"blocked-{tool_name or 'unknown'}"

        if tool_name not in permitted_names or tool_name not in TOOLS_BY_NAME:
            results.append(
                ToolMessage(
                    content=(
                        f"SECURITY BLOCK: Tool '{tool_name or 'unknown'}' is not "
                        f"authorized for intent '{intent}'. The tool was not executed."
                    ),
                    name=tool_name or "unauthorized_tool",
                    tool_call_id=tool_call_id,
                )
            )
            print(
                f"[Security] Blocked unauthorized tool call: {tool_name!r} "
                f"for intent {intent!r}"
            )
            continue

        try:
            tool = TOOLS_BY_NAME[tool_name]
            tool_result = tool.invoke(call.get("args") or {})
            if isinstance(tool_result, str):
                content = tool_result
            else:
                content = str(tool_result)
            results.append(
                ToolMessage(
                    content=content,
                    name=tool_name,
                    tool_call_id=tool_call_id,
                )
            )
        except Exception as exc:
            # Do not leak connection strings, credentials, or full tracebacks
            # to the model as tool output.
            print(f"[Tools] {tool_name} failed: {type(exc).__name__}: {exc}")
            results.append(
                ToolMessage(
                    content=(
                        f"Tool execution failed ({type(exc).__name__}). "
                        "No result is available; check application logs."
                    ),
                    name=tool_name,
                    tool_call_id=tool_call_id,
                )
            )

    return {"messages": results}


print("⚙️ Compiling LangGraph FDE Orchestrator...")
graph_builder = StateGraph(AgentState)
graph_builder.add_node("reasoner", reasoning_node)
graph_builder.add_node("tools", guarded_tool_node)

graph_builder.add_edge(START, "reasoner")
graph_builder.add_conditional_edges("reasoner", tools_condition)
graph_builder.add_edge("tools", "reasoner")

fde_agent = graph_builder.compile(checkpointer=MemorySaver())

# ==========================================
# 4. SYSTEM PROMPT + PER-SESSION TURN BUILDER
#    Shared by the web server (src/ui.py) and the terminal loop below.
# ==========================================
PROMPT_PATH = project_root / "src" / "prompts" / "system_prompt.txt"


def load_system_prompt() -> str:
    """Reads the business-structured system prompt, with a plain fallback if the file is missing."""
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"Warning: could not find {PROMPT_PATH}. Using a basic fallback prompt.")
        return "You are a helpful AI assistant."


SYSTEM_PROMPT = load_system_prompt()

# Safety cap for graph/tool loops. Request-specific instructions further limit
# SQL calls for fleet overviews; this is a final runaway-loop guard.
MAX_GRAPH_STEPS = 12


def build_turn(session_id: str, user_text: str):
    """
    Returns (graph input, run config) for one user turn.
    The system prompt is added exactly once per session: when the session has no history yet.
    """
    config = {
        "configurable": {"thread_id": session_id},
        "recursion_limit": MAX_GRAPH_STEPS,
    }
    snapshot = fde_agent.get_state(config)
    has_history = bool((snapshot.values or {}).get("messages"))
    messages = [] if has_history else [SystemMessage(content=SYSTEM_PROMPT)]
    messages.append(HumanMessage(content=user_text))
    return {"messages": messages}, config


# ==========================================
# 5. CHAT LOOP TESTING PANEL
# ==========================================
if __name__ == "__main__":
    print("\n" + "=" * 55)
    print("🚀 FDE Supply Chain Orchestrator State Machine Online")
    print(
        f"   Configured Execution: [LLM: {AGENT_LLM_SETTING}] -> [Embeddings: {os.getenv('Embeddings_model', 'LOCAL')}]"
    )
    print("=" * 55 + "\n")

    session_id = "production_test_1"

    while True:
        user_input = input("\nDispatcher > ")
        if user_input.lower() in ["exit", "quit"]:
            break

        payload, config = build_turn(session_id, user_input)
        events = fde_agent.stream(payload, config=config, stream_mode="updates")

        for event in events:
            for node_name, node_state in event.items():
                if node_name == "tools":
                    print("\n[System] Tool execution results:")

                    for message in node_state.get("messages", []):
                        tool_name = getattr(message, "name", "unknown_tool")
                        tool_content = getattr(message, "content", "")

                        print(f"\n--- Tool: {tool_name} ---")
                        print(tool_content if tool_content else "[EMPTY TOOL RESULT]")
                        print("-" * 50)

                elif node_name == "reasoner":
                    latest_msg = node_state["messages"][-1]

                    tool_calls = getattr(latest_msg, "tool_calls", [])
                    for call in tool_calls:
                        print(
                            f"\n[System] Requested tool: "
                            f"{call.get('name', 'unknown_tool')}"
                        )
                        print(f"Arguments: {call.get('args', {})}")

                    if latest_msg.content:
                        print(f"\nFDE Agent:\n{latest_msg.content}")
