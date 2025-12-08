"""
Topology Event Extractor - Parse topology_state.jsonl and extract pod lifecycle events.

Extracts simple timeline events:
- Pod created on node X for service A at time T
- Pod crashed on node X for service A at time T
- Pod state change (STARTING -> RUNNING, etc.)
"""

import json
from pathlib import Path
from typing import List, Dict, Optional


def extract_pod_events_from_snapshots(topology_state_file: str) -> List[Dict]:
    """
    Extract pod lifecycle events from topology_state.jsonl snapshots.

    Args:
        topology_state_file: Path to topology_state.jsonl

    Returns:
        List of event dictionaries with:
        - timestamp: Simulation time
        - event_type: pod_created, pod_crashed, pod_terminated, pod_state_change
        - pod_id: Pod identifier
        - service_id: Parent service identifier
        - service_name: Parent service name
        - node_id: Compute node identifier
        - details: Additional event-specific details
    """
    if not Path(topology_state_file).exists():
        return []

    events = []

    # Track previous pod states to detect changes
    prev_pods_by_id = {}

    with open(topology_state_file, 'r') as f:
        for line in f:
            if not line.strip():
                continue

            snapshot = json.loads(line)
            timestamp = snapshot['timestamp']
            snapshot_event = snapshot.get('event', '')

            # Extract events from snapshot event field (direct from TopologyEventTracker)
            if snapshot_event and snapshot_event != 'simulation_start' and snapshot_event != 'simulation_end':
                event = _parse_snapshot_event(snapshot_event, timestamp, snapshot)
                if event:
                    events.append(event)

            # Also detect state changes by comparing snapshots
            current_pods = {pod['id']: pod for pod in snapshot.get('pods', [])}

            for pod_id, pod_state in current_pods.items():
                prev_state = prev_pods_by_id.get(pod_id)

                if not prev_state:
                    # New pod appeared - created
                    events.append({
                        'timestamp': timestamp,
                        'event_type': 'pod_created',
                        'pod_id': pod_id,
                        'service_id': pod_state.get('parent_service_id'),
                        'service_name': pod_state.get('parent_service'),
                        'node_id': pod_state.get('compute_node'),
                        'operational_state': pod_state.get('operational_state'),
                        'details': f"Pod created on {pod_state.get('compute_node')}"
                    })
                else:
                    # Pod existed before, check for changes

                    # Check for restarts (restart count increased)
                    # Only show if restarts > 1 (first startup is restart #1, not a real restart)
                    prev_restarts = prev_state.get('restarts', 0)
                    curr_restarts = pod_state.get('restarts', 0)
                    if prev_restarts < curr_restarts and curr_restarts > 1:
                        events.append({
                            'timestamp': timestamp,
                            'event_type': 'pod_restarted',
                            'pod_id': pod_id,
                            'service_id': pod_state.get('parent_service_id'),
                            'service_name': pod_state.get('parent_service'),
                            'node_id': pod_state.get('compute_node'),
                            'operational_state': pod_state.get('operational_state'),
                            'restarts': curr_restarts,
                            'details': f"Pod restarted (total restarts: {curr_restarts})"
                        })

                    if prev_state['operational_state'] != pod_state['operational_state']:
                        old_state = prev_state['operational_state']
                        new_state = pod_state['operational_state']

                        # Skip INITIALIZING → STARTING and STARTING → RUNNING (normal startup, too noisy)
                        skip_transitions = [
                            ('INITIALIZING', 'STARTING'),
                            ('STARTING', 'RUNNING'),
                            ('INITIALIZING', 'RUNNING')  # Inferred from snapshot diff
                        ]

                        if (old_state, new_state) not in skip_transitions:
                            # State transition (only show interesting ones)
                            events.append({
                                'timestamp': timestamp,
                                'event_type': 'pod_state_change',
                                'pod_id': pod_id,
                                'service_id': pod_state.get('parent_service_id'),
                                'service_name': pod_state.get('parent_service'),
                                'node_id': pod_state.get('compute_node'),
                                'operational_state': pod_state.get('operational_state'),
                                'old_state': old_state,
                                'new_state': new_state,
                                'details': f"{old_state} → {new_state}"
                            })

                        # Special handling for crashes and failures
                        if new_state in ('CRASHED', 'TERMINATED', 'DOWN'):
                            event_type_map = {
                                'CRASHED': 'pod_crashed',
                                'TERMINATED': 'pod_terminated',
                                'DOWN': 'pod_crashed'
                            }
                            events.append({
                                'timestamp': timestamp,
                                'event_type': event_type_map.get(new_state, 'pod_crashed'),
                                'pod_id': pod_id,
                                'service_id': pod_state.get('parent_service_id'),
                                'service_name': pod_state.get('parent_service'),
                                'node_id': pod_state.get('compute_node'),
                                'operational_state': new_state,
                                'restarts': pod_state.get('restarts', 0),
                                'details': f"Pod {new_state.lower()} on {pod_state.get('compute_node')} (restarts: {pod_state.get('restarts', 0)})"
                            })

                    if prev_state.get('compute_node') != pod_state.get('compute_node'):
                        # Pod moved to different node (rescheduled)
                        events.append({
                            'timestamp': timestamp,
                            'event_type': 'pod_rescheduled',
                            'pod_id': pod_id,
                            'service_id': pod_state.get('parent_service_id'),
                            'service_name': pod_state.get('parent_service'),
                            'node_id': pod_state.get('compute_node'),
                            'operational_state': pod_state.get('operational_state'),
                            'old_node': prev_state.get('compute_node'),
                            'new_node': pod_state.get('compute_node'),
                            'details': f"Rescheduled from {prev_state.get('compute_node')} to {pod_state.get('compute_node')}"
                        })

            # Detect terminated pods (present in prev, absent in current)
            for pod_id, prev_state in prev_pods_by_id.items():
                if pod_id not in current_pods:
                    events.append({
                        'timestamp': timestamp,
                        'event_type': 'pod_terminated',
                        'pod_id': pod_id,
                        'service_id': prev_state.get('parent_service_id'),
                        'service_name': prev_state.get('parent_service'),
                        'node_id': prev_state.get('compute_node'),
                        'operational_state': 'TERMINATED',
                        'details': f"Pod terminated from {prev_state.get('compute_node')}"
                    })

            # Update tracking
            prev_pods_by_id = current_pods

    # Sort events by timestamp
    events.sort(key=lambda e: e['timestamp'])

    return events


def _parse_snapshot_event(event_str: str, timestamp: float, snapshot: Dict) -> Optional[Dict]:
    """
    Parse event string from topology snapshot (e.g., 'pod_created:pod_a_0@service_a→node_0').

    Returns event dictionary or None if not parseable.
    """
    if ':' not in event_str:
        return None

    event_type, details = event_str.split(':', 1)

    # Extract pod_id from details
    pod_id = None
    if '@' in details:
        pod_id = details.split('@')[0]
    elif '→' in details:
        pod_id = details.split('→')[0].split(':')[-1]

    if not pod_id:
        return None

    # Find pod in snapshot to get service/node info
    pod_state = None
    for pod in snapshot.get('pods', []):
        if pod['id'] == pod_id:
            pod_state = pod
            break

    if not pod_state:
        return None

    return {
        'timestamp': timestamp,
        'event_type': event_type,
        'pod_id': pod_id,
        'service_id': pod_state.get('parent_service_id'),
        'service_name': pod_state.get('parent_service'),
        'node_id': pod_state.get('compute_node'),
        'operational_state': pod_state.get('operational_state'),
        'details': details
    }


def group_events_by_service(events: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Group pod lifecycle events by service.

    Args:
        events: List of event dictionaries

    Returns:
        Dictionary mapping service_id to list of events for that service
    """
    by_service = {}

    for event in events:
        service_id = event.get('service_id')
        if service_id:
            if service_id not in by_service:
                by_service[service_id] = []
            by_service[service_id].append(event)

    return by_service


def get_service_timeline_summary(service_events: List[Dict]) -> Dict:
    """
    Summarize pod events for a service.

    Args:
        service_events: List of events for a single service

    Returns:
        Summary dictionary with counts and timeline
    """
    if not service_events:
        return {
            'total_events': 0,
            'event_counts': {},
            'pod_count': 0,
            'timeline': []
        }

    # Count event types
    event_counts = {}
    for event in service_events:
        event_type = event['event_type']
        event_counts[event_type] = event_counts.get(event_type, 0) + 1

    # Count unique pods
    unique_pods = set(e['pod_id'] for e in service_events)

    return {
        'total_events': len(service_events),
        'event_counts': event_counts,
        'pod_count': len(unique_pods),
        'timeline': service_events,
        'service_name': service_events[0].get('service_name', 'unknown')
    }


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python topology_event_extractor.py <topology_state.jsonl>")
        sys.exit(1)

    topology_file = sys.argv[1]

    print(f"Extracting events from {topology_file}...")
    events = extract_pod_events_from_snapshots(topology_file)

    print(f"\nFound {len(events)} total events")

    # Group by service
    by_service = group_events_by_service(events)
    print(f"\nEvents by service:")
    for service_id, service_events in by_service.items():
        summary = get_service_timeline_summary(service_events)
        print(f"  {service_id} ({summary['service_name']}): {summary['total_events']} events, {summary['pod_count']} pods")
        print(f"    Event types: {summary['event_counts']}")

    # Show first few events
    print(f"\nFirst 10 events:")
    for event in events[:10]:
        print(f"  t={event['timestamp']:.1f}s: {event['event_type']} - {event['pod_id']} ({event['service_name']}) - {event['details']}")
