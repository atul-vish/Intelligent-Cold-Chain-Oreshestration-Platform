import json
import statistics
import time
import urllib.request
import uuid

URL = "http://127.0.0.1:8000/api/chat"

questions = [
    "What are the temperature rules for fresh perishables?",
    "What should a dispatcher do when a cold-chain temperature breach occurs?",
    "Explain the mitigation protocol for refrigerated cargo.",
    "What should happen when cargo temperature exceeds the approved range?",
    "Summarize the relevant cold-chain incident SOP requirements.",
]

results = []

for i, question in enumerate(questions, start=1):
    # A unique session guarantees an independent conversation.
    session_id = f"bench-{uuid.uuid4().hex[:16]}"

    payload = {
        "session_id": session_id,
        "message": question,
    }

    request = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    start = time.perf_counter()

    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = response.read().decode("utf-8")
            status = response.status

        elapsed = time.perf_counter() - start

        events = []
        malformed_lines = []

        for line in body.splitlines():
            if not line.strip():
                continue

            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                malformed_lines.append(line)

        tool_inputs = [
            event for event in events
            if event.get("type") == "tool_input"
        ]

        tool_outputs = [
            event for event in events
            if event.get("type") == "tool_output"
        ]

        final_events = [
            event for event in events
            if event.get("type") == "final"
        ]

        error_events = [
            event for event in events
            if event.get("type") == "error"
        ]

        result = {
            "question": question,
            "session_id": session_id,
            "latency": elapsed,
            "status": status,
            "tool_inputs": len(tool_inputs),
            "tool_outputs": len(tool_outputs),
            "has_final": bool(final_events),
            "has_error": bool(error_events),
        }
        results.append(result)

        print(f"\nRequest {i}: {elapsed:.2f}s")
        print(f"Session ID: {session_id}")
        print(f"Question: {question}")
        print(f"HTTP status: {status}")
        print(f"Tool-input events: {len(tool_inputs)}")
        print(f"Tool-output events: {len(tool_outputs)}")
        print(f"Final answer received: {bool(final_events)}")
        print(f"API error event: {bool(error_events)}")

        if final_events:
            print("Answer preview:")
            print(final_events[-1].get("content", "")[:250])

        if error_events:
            print("Error details:")
            print(error_events[-1].get("message", "Unknown error"))

        if malformed_lines:
            print(
                f"Warning: {len(malformed_lines)} "
                "response line(s) were not valid JSON."
            )

    except Exception as exc:
        print(f"\nRequest {i} failed: {type(exc).__name__}: {exc}")

if results:
    latencies = [result["latency"] for result in results]

    print("\n--- END-TO-END LATENCY SUMMARY ---")
    print(f"Successful HTTP responses: {len(results)}/{len(questions)}")
    print(f"Average: {statistics.mean(latencies):.2f}s")
    print(f"Median: {statistics.median(latencies):.2f}s")
    print(f"Minimum: {min(latencies):.2f}s")
    print(f"Maximum: {max(latencies):.2f}s")

    print(
        "Responses with final answers: "
        f"{sum(r['has_final'] for r in results)}/{len(results)}"
    )
    print(
        "Responses with tool-input events: "
        f"{sum(r['tool_inputs'] > 0 for r in results)}/{len(results)}"
    )
    print(
        "Responses with tool-output events: "
        f"{sum(r['tool_outputs'] > 0 for r in results)}/{len(results)}"
    )