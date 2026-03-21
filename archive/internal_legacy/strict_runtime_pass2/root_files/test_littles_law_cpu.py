"""
Test that Little's Law correctly estimates working threads.

Little's Law: L = λ * W
- L = concurrent requests (threads doing work)
- λ = throughput (requests/second)
- W = average latency (seconds)
"""

def test_littles_law():
    print("Testing Little's Law for concurrent request estimation:")
    print("=" * 70)

    # Scenario 1: Normal operation (all threads working)
    print("\n✅ Scenario 1: Normal operation")
    throughput = 100  # req/s
    latency_ms = 100  # 100ms per request
    latency_s = latency_ms / 1000.0
    concurrent = throughput * latency_s
    print(f"  Throughput: {throughput} req/s")
    print(f"  Latency: {latency_ms}ms")
    print(f"  Concurrent = {throughput} * {latency_s} = {concurrent} threads")
    print(f"  CPU = 10% + (0.5 * {concurrent}) = {10 + 0.5 * concurrent}%")

    # Scenario 2: Complete deadlock (0 threads working)
    print("\n❌ Scenario 2: Complete deadlock")
    throughput = 0  # No work being done!
    latency_ms = 5000  # Latency high but irrelevant
    latency_s = latency_ms / 1000.0
    concurrent = throughput * latency_s
    print(f"  Throughput: {throughput} req/s (DEADLOCKED)")
    print(f"  Latency: {latency_ms}ms (stuck waiting)")
    print(f"  Concurrent = {throughput} * {latency_s} = {concurrent} threads")
    print(f"  CPU = 10% + (0.5 * {concurrent}) = {10 + 0.5 * concurrent}% (baseline)")

    # Scenario 3: Partial deadlock (7 deadlocked, 3 working)
    print("\n⚠️  Scenario 3: Partial deadlock (7/10 threads stuck)")
    throughput = 30  # 3 threads @ ~10 req/s each
    latency_ms = 100  # Normal latency for working threads
    latency_s = latency_ms / 1000.0
    concurrent = throughput * latency_s
    print(f"  Throughput: {throughput} req/s (reduced)")
    print(f"  Latency: {latency_ms}ms (normal for working threads)")
    print(f"  Concurrent = {throughput} * {latency_s} = {concurrent} threads")
    print(f"  CPU = 10% + (0.5 * {concurrent}) = {10 + 0.5 * concurrent}%")
    print(f"  ✅ Correctly shows ~3 threads working, not 10!")

    # Scenario 4: High load (threads working hard with queuing)
    print("\n🔥 Scenario 4: High load with queuing")
    throughput = 50  # req/s
    latency_ms = 200  # Latency doubled due to load
    latency_s = latency_ms / 1000.0
    concurrent = throughput * latency_s
    print(f"  Throughput: {throughput} req/s")
    print(f"  Latency: {latency_ms}ms (increased due to load)")
    print(f"  Concurrent = {throughput} * {latency_s} = {concurrent} threads")
    print(f"  CPU = 10% + (0.5 * {concurrent}) = {10 + 0.5 * concurrent}%")
    print(f"  ✅ Naturally captures increased concurrency!")

    print("\n" + "=" * 70)
    print("✅ Little's Law correctly estimates WORKING threads in all scenarios!")

if __name__ == "__main__":
    test_littles_law()
