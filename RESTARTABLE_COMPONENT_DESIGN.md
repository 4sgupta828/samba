# First-Principles Design: Restartable Components

## The Problem (Universal)

**ALL components that can restart** suffer from the same fundamental issue:

```
┌─────────────────────────────────────────┐
│ Python Object (persists)                │
│                                         │
│  def run(self):                         │
│    while True:  ← Restart loop         │
│      self.state = "STARTING"           │
│      # State from previous iteration   │
│      # persists here! ❌               │
│      yield timeout(startup)            │
│      self.state = "RUNNING"            │
│      yield timeout(3600)  # or crash   │
└─────────────────────────────────────────┘
```

**Affected components:**
- Pod (containers)
- Database (DB processes can crash/restart)
- MessageQueue (queue server can crash/restart)
- Cache (Redis/Memcached can crash/restart)
- Any future component with lifecycle management

## First-Principles Design

### Core Principle:

**"Each restart should be indistinguishable from creating a new process"**

### Architecture: Component Lifecycle Manager Pattern

```
┌────────────────────────────────────────────────────┐
│ ComponentLifecycleManager (Persistent)             │
│  - Manages restart policy                          │
│  - Tracks restart count                            │
│  - Handles backoff delays                          │
│  - Maintains identity (component_id)               │
│                                                     │
│  Creates ↓                                          │
├────────────────────────────────────────────────────┤
│ ComponentInstance (Ephemeral)                      │
│  - Fresh state on each instantiation               │
│  - Runs single lifetime                            │
│  - Garbage collected on termination                │
│  - Cannot leak state (impossible!)                 │
└────────────────────────────────────────────────────┘
```

## Implementation Design

### 1. Base Classes

```python
# File: src/components/lifecycle.py

from abc import ABC, abstractmethod
from typing import Optional, Any, Dict
import simpy


class RestartableComponent(ABC):
    """
    Base class for components that can be restarted (Pods, Databases, etc.).

    This is the EPHEMERAL instance that lives for a single lifetime.
    It is created fresh on each restart and garbage collected when terminated.
    """

    def __init__(self, env: simpy.Environment, component_id: str,
                 component_type: str, lifetime_id: int):
        """
        Initialize component instance for a single lifetime.

        Args:
            env: SimPy environment
            component_id: Persistent component identifier
            component_type: Type of component (Pod, Database, etc.)
            lifetime_id: Which lifetime this is (0 = first start, 1 = first restart, etc.)
        """
        self.env = env
        self.component_id = component_id  # Persistent ID
        self.lifetime_id = lifetime_id    # Which incarnation
        self.component_type = component_type

        # Full ID includes lifetime
        self.instance_id = f"{component_id}_L{lifetime_id}"

        # Initialize fresh state
        self._initialize_fresh_state()

        print(f"Created {component_type} instance: {self.instance_id}")

    @abstractmethod
    def _initialize_fresh_state(self):
        """
        Initialize all mutable state for this lifetime.

        This method MUST initialize ALL state variables to their starting values.
        This is called once during __init__ and never again.

        Example:
            self.thread_pool = simpy.Resource(self.env, capacity=50)
            self.request_count = 0
            self.active_processes = set()
        """
        pass

    @abstractmethod
    def run_single_lifetime(self):
        """
        Run component for a single lifetime (until crash or termination).

        This is a SimPy generator that runs until:
        - Interrupted with "CRASHED" cause (restart)
        - Interrupted with "TERMINATED" cause (permanent stop)
        - Completes naturally (rare)

        Returns control to ComponentLifecycleManager when done.
        """
        pass

    @abstractmethod
    def get_persistent_config(self) -> Dict[str, Any]:
        """
        Return configuration that should persist across restarts.

        This is used to initialize the next instance after restart.
        Only include immutable configuration, NOT runtime state.

        Example:
            return {
                'thread_pool_size': self.thread_pool_size,
                'memory_capacity': self.memory_capacity,
                'parent_service': self.parent_service,
            }
        """
        pass


class ComponentLifecycleManager:
    """
    Manages the lifecycle of a restartable component.

    This is the PERSISTENT manager that survives across restarts.
    It creates fresh ComponentInstance objects on each restart.
    """

    def __init__(self, env: simpy.Environment, component_id: str,
                 component_type: str, component_class: type,
                 persistent_config: Dict[str, Any],
                 restart_policy: Optional[Dict[str, Any]] = None):
        """
        Initialize lifecycle manager.

        Args:
            env: SimPy environment
            component_id: Unique identifier for this component
            component_type: Type of component (Pod, Database, etc.)
            component_class: Class to instantiate (must inherit RestartableComponent)
            persistent_config: Configuration that persists across restarts
            restart_policy: Restart policy configuration
        """
        self.env = env
        self.component_id = component_id
        self.component_type = component_type
        self.component_class = component_class
        self.persistent_config = persistent_config

        # Restart policy
        self.restart_policy = restart_policy or {
            'max_restarts': None,  # None = unlimited
            'backoff_base_seconds': 10.0,
            'backoff_max_seconds': 300.0,
            'backoff_jitter_range': [-2, 5],
        }

        # Lifecycle tracking
        self.lifetime_count = 0
        self.total_restarts = 0
        self.current_instance: Optional[RestartableComponent] = None
        self.termination_requested = False

        # Callbacks for lifecycle events
        self.on_instance_created = None
        self.on_instance_terminated = None

    def run(self):
        """
        Main lifecycle loop - creates and manages component instances.

        This is a SimPy generator that runs forever (or until terminated).
        """
        while not self.termination_requested:
            # Create new instance for this lifetime
            self.current_instance = self.component_class(
                env=self.env,
                component_id=self.component_id,
                component_type=self.component_type,
                lifetime_id=self.lifetime_count,
                **self.persistent_config  # Pass persistent config
            )

            # Notify listeners
            if self.on_instance_created:
                self.on_instance_created(self.current_instance)

            try:
                # Run instance for single lifetime
                yield self.env.process(self.current_instance.run_single_lifetime())

                # If we get here, instance completed naturally (rare)
                print(f"{self.component_type} {self.component_id} completed lifetime {self.lifetime_count}")
                break  # Exit lifecycle loop

            except simpy.Interrupt as interrupt:
                cause = interrupt.cause

                if cause == "TERMINATED":
                    # Permanent termination requested
                    print(f"{self.component_type} {self.component_id} terminated at lifetime {self.lifetime_count}")
                    break  # Exit lifecycle loop

                elif cause in ["CRASHED", "OOMKilled", "Error"]:
                    # Component crashed - prepare for restart
                    print(f"{self.component_type} {self.component_id} crashed at lifetime {self.lifetime_count}: {cause}")

                    self.total_restarts += 1

                    # Check restart limit
                    if self.restart_policy['max_restarts'] is not None:
                        if self.total_restarts >= self.restart_policy['max_restarts']:
                            print(f"{self.component_type} {self.component_id} exceeded max restarts ({self.restart_policy['max_restarts']})")
                            break  # Exit lifecycle loop

                    # Calculate backoff delay (exponential with jitter)
                    backoff_base = self.restart_policy['backoff_base_seconds']
                    backoff_max = self.restart_policy['backoff_max_seconds']
                    jitter_range = self.restart_policy['backoff_jitter_range']

                    backoff = min(backoff_base * (2 ** self.total_restarts), backoff_max)
                    jitter = random.uniform(jitter_range[0], jitter_range[1])
                    delay = backoff + jitter

                    print(f"{self.component_type} {self.component_id} waiting {delay:.1f}s before restart #{self.total_restarts + 1}")

                    # Wait for backoff
                    yield self.env.timeout(delay)

                    # Notify listeners
                    if self.on_instance_terminated:
                        self.on_instance_terminated(self.current_instance)

                    # Instance object goes out of scope here and will be garbage collected
                    # ALL its state is destroyed!
                    self.current_instance = None

                    # Increment lifetime counter
                    self.lifetime_count += 1

                    # Continue to next iteration (create new instance)

                else:
                    # Unknown interrupt cause
                    print(f"{self.component_type} {self.component_id} received unknown interrupt: {cause}")
                    break  # Exit lifecycle loop

            finally:
                # Cleanup
                if self.on_instance_terminated and self.current_instance:
                    self.on_instance_terminated(self.current_instance)
                self.current_instance = None

        print(f"{self.component_type} {self.component_id} lifecycle ended (total restarts: {self.total_restarts})")

    def terminate(self):
        """Request termination of the component (graceful shutdown)."""
        self.termination_requested = True
        if self.current_instance:
            # Interrupt current instance
            # Note: Need to get process handle somehow
            pass
```

### 2. Example: Restartable Pod

```python
# File: src/components/pod_restartable.py

from src.components.lifecycle import RestartableComponent
from src.core.simulation_config import get_simulation_config
import simpy


class RestartablePod(RestartableComponent):
    """
    Pod implementation using RestartableComponent pattern.

    Each instance is a fresh process with no state from previous lifetimes.
    """

    def __init__(self, env, component_id, component_type, lifetime_id,
                 parent_service=None, compute_node=None, **kwargs):
        # Store persistent references
        self.parent_service = parent_service
        self.compute_node = compute_node

        # Initialize base
        super().__init__(env, component_id, component_type, lifetime_id)

        # Register with parent
        if self.parent_service:
            self.parent_service.register_pod_instance(self)
        if self.compute_node:
            self.compute_node.register_pod_instance(self)

    def _initialize_fresh_state(self):
        """Initialize ALL mutable state for this lifetime."""
        config = get_simulation_config().compute

        # Resource pools (FRESH instances!)
        self.thread_pool = simpy.Resource(self.env, capacity=config.thread_pool_size)
        self.db_connection_pool = simpy.Resource(self.env, capacity=config.db_connection_pool_capacity)

        # Tracking structures (EMPTY!)
        self.active_request_processes = set()
        self.cpu_samples = []
        self.memory_samples = []
        self.connection_pool_samples = []
        self.connection_queue_samples = []

        # Counters (RESET to 0!)
        self.request_count = 0
        self.last_request_count = 0

        # State
        self.state = MultiDimensionalState()
        self.state.operational = "STARTING"

        # Dynamics engine (FRESH instance!)
        self.dynamics = MetricsDynamicsEngine(config=self._get_dynamics_config())

        # Circuit breakers (EMPTY!)
        self._circuit_breakers = {}
        self._retry_policies = {}

        # Metrics (fresh)
        self._initialize_metrics()

        print(f"Pod {self.instance_id}: Fresh state initialized")

    def run_single_lifetime(self):
        """Run pod for a single lifetime (until crash or termination)."""
        config = get_simulation_config().compute

        # Startup phase
        self.state.operational = "STARTING"
        startup_delay = random.uniform(*config.startup_time_range_seconds)
        yield self.env.timeout(startup_delay)

        self.state.operational = "RUNNING"
        print(f"Pod {self.instance_id}: Started successfully")

        # Start background processes
        self.env.process(self._sample_cpu_periodically())
        self.env.process(self._monitor_oom())

        # Run until interrupted (crash or termination)
        try:
            # Wait for interrupt
            yield self.env.timeout(float('inf'))
        except simpy.Interrupt as interrupt:
            # Re-raise to be handled by lifecycle manager
            raise

    def get_persistent_config(self):
        """Return config that persists across restarts."""
        return {
            'parent_service': self.parent_service,
            'compute_node': self.compute_node,
            # Add other immutable config here
        }

    def handle_request(self, request_type, ...):
        """Handle incoming request (same as before)."""
        # Implementation unchanged
        pass

    # ... rest of Pod implementation ...
```

### 3. Usage Example

```python
# In topology setup:

# Old way (buggy):
pod = Pod(env, "pod_1", parent_service=service)
env.process(pod.run())  # Has while True loop inside

# New way (correct):
pod_manager = ComponentLifecycleManager(
    env=env,
    component_id="pod_1",
    component_type="Pod",
    component_class=RestartablePod,
    persistent_config={
        'parent_service': service,
        'compute_node': node,
    },
    restart_policy={
        'max_restarts': None,  # Unlimited
        'backoff_base_seconds': 10.0,
        'backoff_max_seconds': 300.0,
    }
)

# Register callbacks for service to track instances
def on_pod_created(pod_instance):
    service.active_pods.append(pod_instance)

def on_pod_terminated(pod_instance):
    service.active_pods.remove(pod_instance)

pod_manager.on_instance_created = on_pod_created
pod_manager.on_instance_terminated = on_pod_terminated

# Start lifecycle manager
env.process(pod_manager.run())

# To trigger crash:
current_pod = pod_manager.current_instance
current_pod.trigger_crash("OOMKilled")  # Creates new instance automatically

# To terminate permanently:
pod_manager.terminate()
```

## Benefits of This Design

### 1. **Impossible to Leak State**
```python
# Old way (can leak):
class Pod:
    def run(self):
        while True:  # Same object reused
            # Need to manually clear EVERYTHING
            self.thread_pool.queue.clear()  # Easy to forget!
            self.thread_pool.users.clear()  # Did you remember?
            self._circuit_breakers.clear()  # What about this?
            # ... 20+ more things to clear ...

# New way (cannot leak):
class RestartablePod:
    def _initialize_fresh_state(self):
        # Create everything fresh
        self.thread_pool = simpy.Resource(...)  # NEW object
        self.active_processes = set()  # NEW set
        # Python GC destroys old instance, impossible to leak!
```

### 2. **Clear Separation of Concerns**
- **ComponentLifecycleManager**: Restart policy, backoff, lifecycle
- **ComponentInstance**: Single-lifetime logic only

### 3. **Uniform Pattern for All Components**
```python
# Pod
pod_mgr = ComponentLifecycleManager(..., component_class=RestartablePod)

# Database
db_mgr = ComponentLifecycleManager(..., component_class=RestartableDatabase)

# MessageQueue
queue_mgr = ComponentLifecycleManager(..., component_class=RestartableMessageQueue)

# Same pattern everywhere!
```

### 4. **Easier Testing**
```python
# Test single lifetime (no restart complexity)
pod = RestartablePod(env, "test_pod", "Pod", lifetime_id=0, ...)
env.process(pod.run_single_lifetime())
env.run(until=100)
# No need to mock restart logic

# Test lifecycle management separately
mgr = ComponentLifecycleManager(...)
# Test restart policy, backoff, etc.
```

### 5. **Better Matches Real World**
```
Kubernetes:
┌──────────────────┐
│ Pod Controller   │  ← ComponentLifecycleManager
│ - Restart policy │
│ - Backoff        │
└────────┬─────────┘
         │ creates
         ▼
┌──────────────────┐
│ Container (PID)  │  ← RestartablePod instance
│ - Fresh process  │
│ - Dies on crash  │
└──────────────────┘
```

## Migration Strategy

### Phase 1: Add New Pattern (No Breaking Changes)
```python
# New components use RestartableComponent
class RestartablePod(RestartableComponent):
    pass

# Old components still work
class Pod(EnrichedComponent):
    pass  # Legacy
```

### Phase 2: Deprecate Old Pattern
```python
# Add deprecation warnings
class Pod(EnrichedComponent):
    def __init__(self, ...):
        warnings.warn("Pod is deprecated, use RestartablePod with ComponentLifecycleManager")
        super().__init__(...)
```

### Phase 3: Migrate Existing Components
1. Pod → RestartablePod
2. Database → RestartableDatabase
3. MessageQueue → RestartableMessageQueue
4. Cache → RestartableCache

### Phase 4: Remove Old Pattern
```python
# Delete old implementations
# All components use RestartableComponent pattern
```

## Implementation Checklist

### Core Infrastructure:
- [ ] Create `src/components/lifecycle.py`
- [ ] Implement `RestartableComponent` base class
- [ ] Implement `ComponentLifecycleManager`
- [ ] Add tests for lifecycle management

### Component Migrations:
- [ ] Migrate `Pod` → `RestartablePod`
- [ ] Migrate `Database` → `RestartableDatabase`
- [ ] Migrate `MessageQueue` → `RestartableMessageQueue`
- [ ] Migrate `Cache` → `RestartableCache`

### Integration:
- [ ] Update topology setup to use managers
- [ ] Update Service to track instances correctly
- [ ] Update metrics collection
- [ ] Update failure injection

### Testing:
- [ ] Test state isolation (verify no leaks)
- [ ] Test restart policy
- [ ] Test crash scenarios
- [ ] Test permanent termination

### Documentation:
- [ ] Developer guide for creating restartable components
- [ ] Migration guide for existing code
- [ ] Architecture documentation

## Comparison: Old vs New

| Aspect | Old Design | New Design |
|--------|-----------|------------|
| **State isolation** | Manual, error-prone | Automatic, guaranteed |
| **Restart logic** | Mixed with component | Separated in manager |
| **State leaks** | Easy to introduce | Impossible |
| **Testing** | Complex (must test restart) | Simple (test lifetime separately) |
| **Code clarity** | while True loop confusing | Clear single-lifetime semantics |
| **Real-world match** | Poor | Excellent |
| **Maintainability** | Hard (must remember to clear everything) | Easy (just initialize fresh) |

## Conclusion

This design:
1. ✅ **Solves the root cause** (not a patch)
2. ✅ **Works for all components** (uniform pattern)
3. ✅ **Cannot leak state** (Python GC ensures this)
4. ✅ **Matches real-world behavior** (process death = state loss)
5. ✅ **Makes code simpler** (no manual state management)
6. ✅ **Easier to test** (test lifetime and lifecycle separately)
7. ✅ **Maintainable** (new state variables automatically handled)

**This is the "right" way to model component lifecycles in SimPy.**
