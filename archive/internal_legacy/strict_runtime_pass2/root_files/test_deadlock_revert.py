"""
Test script to verify thread_exhaustion and revert_thread_exhaustion work correctly.
"""
import simpy
from src.components.service import Service
from src.components.pod import Pod
from src.failures.modes import thread_exhaustion, revert_thread_exhaustion

def test_thread_exhaustion_revert():
    """Test that thread_exhaustion can be reverted properly."""
    env = simpy.Environment()

    # Create a minimal pod with required attributes
    class MockPod(Pod):
        def __init__(self, env, pod_id):
            self.env = env
            self.id = pod_id
            self.thread_pool = simpy.Resource(env, capacity=10)
            self._zombie_processes = []

        def _emit_log(self, level, message):
            print(f"[{self.env.now:.1f}s] [{level}] {self.id}: {message}")

    # Create a minimal service
    class MockService(Service):
        def __init__(self, env, service_id):
            self.env = env
            self.id = service_id
            self.pods = []

        def _emit_log(self, level, message):
            print(f"[{self.env.now:.1f}s] [{level}] {self.id}: {message}")

    # Create service and pod
    service = MockService(env, "test_service")
    pod = MockPod(env, "test_pod_0")
    service.pods.append(pod)

    print("=== Initial state ===")
    print(f"Thread pool capacity: {pod.thread_pool.capacity}")
    print(f"Thread pool count (in use): {pod.thread_pool.count}")

    # Apply thread_exhaustion using percentage-based approach
    print("\n=== Applying thread_exhaustion at t=10s (70% of threads) ===")
    env.run(until=10)
    thread_exhaustion(service, {"thread_percentage": 0.7, "duration": 100.0})

    # Run simulation to let thread_exhaustion take effect
    env.run(until=11)
    expected_locked = int(10 * 0.7)  # 70% of 10 = 7 threads
    print(f"\nThread pool count after thread_exhaustion: {pod.thread_pool.count} (expected: {expected_locked})")
    print(f"Zombie processes: {len(pod._zombie_processes)} (expected: {expected_locked})")
    print(f"_force_deadlock_pod_id on service: {getattr(service, '_force_deadlock_pod_id', 'NOT SET')}")

    # Revert thread_exhaustion
    print("\n=== Reverting thread_exhaustion at t=20s ===")
    env.run(until=20)
    revert_thread_exhaustion(service, {})

    # Check if threads were released
    env.run(until=21)
    print(f"\nThread pool count after revert: {pod.thread_pool.count}")
    print(f"Zombie processes after revert: {len(pod._zombie_processes)}")
    print(f"_force_deadlock_pod_id on service: {getattr(service, '_force_deadlock_pod_id', 'NOT SET')}")

    # Run longer to ensure processes are truly dead
    env.run(until=30)
    print(f"\nThread pool count at t=30s: {pod.thread_pool.count}")

    # Success check
    if pod.thread_pool.count == 0 and len(pod._zombie_processes) == 0:
        print("\n✅ SUCCESS: Thread exhaustion properly reverted!")
    else:
        print(f"\n❌ FAILURE: Threads still locked (count={pod.thread_pool.count}, zombies={len(pod._zombie_processes)})")

if __name__ == "__main__":
    test_thread_exhaustion_revert()
