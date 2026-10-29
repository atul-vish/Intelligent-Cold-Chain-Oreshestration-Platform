import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from typing import Annotated, TypedDict
import time
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
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
        "🐳 Brain Mode: Utilizing DeepSeek Flash (configured model: deepseek-flash)..."
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

fde_tools = [query_telemetry_db, fetch_corridor_conditions, search_compliance_sop]
llm_with_tools = llm.bind_tools(fde_tools)


# ==========================================
# 3. GRAPH ARCHITECTURE ASSEMBLY
# ==========================================


def reasoning_node(state: AgentState):
    start = time.perf_counter()
    response = llm_with_tools.invoke(state["messages"])
    elapsed = time.perf_counter() - start

    tool_calls = getattr(response, "tool_calls", None) or []
    usage = getattr(response, "usage_metadata", None) or {}

    input_tokens = usage.get("input_tokens", "N/A")
    output_tokens = usage.get("output_tokens", "N/A")

    print(
        f"[PERF] LLM reasoning: {elapsed:.3f}s | "
        f"Input messages: {len(state['messages'])} | "
        f"Tool calls: {len(tool_calls)} | "
        f"Input tokens: {input_tokens} | "
        f"Output tokens: {output_tokens}",
        flush=True,
    )

    return {"messages": [response]}


print("⚙️ Compiling LangGraph FDE Orchestrator...")
graph_builder = StateGraph(AgentState)
graph_builder.add_node("reasoner", reasoning_node)
graph_builder.add_node("tools", ToolNode(fde_tools))

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

# Caps tool-call loops so one confused turn cannot run forever.
MAX_GRAPH_STEPS = 14


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
                    print(
                        "   [System] 🔄 Retrieving external data elements via ToolNode..."
                    )
                elif node_name == "reasoner":
                    latest_msg = node_state["messages"][-1]
                    if latest_msg.content:
                        print(f"\n🤖 FDE Agent:\n{latest_msg.content}")
