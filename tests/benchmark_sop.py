import time
from src.agent_tools import search_compliance_sop

query = "What are the temperature rules for fresh perishables?"
times = []
results = []

for i in range(5):
    start = time.perf_counter()

    result = search_compliance_sop.invoke({"query": query})

    elapsed = time.perf_counter() - start
    times.append(elapsed)
    results.append(result)

    print(f"Run {i + 1}: {elapsed:.3f}s | {len(result)} characters")

print(f"\nAverage: {sum(times) / len(times):.3f}s")
print(f"Minimum: {min(times):.3f}s")
print(f"Maximum: {max(times):.3f}s")
print(f"All results identical: {all(r == results[0] for r in results)}")
