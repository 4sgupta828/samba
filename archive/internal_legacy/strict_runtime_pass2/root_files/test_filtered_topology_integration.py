#!/usr/bin/env python3
"""
Test script to validate filtered topology integration with the UI.
"""

import sys
sys.path.insert(0, 'viz')

from data_loader import load_episode, list_data_runs, list_episodes

def test_filtered_topology_integration():
    """Test that filtered topology is properly loaded and integrated."""
    print("Testing Filtered Topology Integration")
    print("=" * 60)

    # Find data runs
    base_dir = "data"
    runs = list_data_runs(base_dir)

    if not runs:
        print("❌ No data runs found")
        return False

    print(f"✓ Found {len(runs)} data run(s)")

    # Use the most recent run
    run_path = runs[0]['path']
    print(f"✓ Using data run: {runs[0]['id']}")

    # List episodes
    episodes = list_episodes(run_path)
    if not episodes:
        print("❌ No episodes found")
        return False

    print(f"✓ Found {len(episodes)} episode(s)")

    # Test each episode
    all_passed = True
    for ep_id in episodes[:3]:  # Test first 3 episodes
        print(f"\n--- Testing {ep_id} ---")

        try:
            # Load episode data
            episode_data = load_episode(ep_id, run_path)
            print(f"✓ Loaded episode data")

            # Check if filtered topology exists
            has_filtered = episode_data.get('has_filtered_topology', False)
            print(f"{'✓' if has_filtered else '✗'} Filtered topology available: {has_filtered}")

            if has_filtered:
                # Validate filtered topology
                filtered_topo = episode_data['topology_filtered']
                filtered_graph = episode_data['topology_graph_filtered']

                original_nodes = episode_data['topology_graph'].number_of_nodes()
                filtered_nodes = filtered_graph.number_of_nodes()

                print(f"  Original nodes: {original_nodes}")
                print(f"  Filtered nodes: {filtered_nodes}")
                print(f"  Reduction: {original_nodes - filtered_nodes} nodes ({(original_nodes - filtered_nodes) / original_nodes * 100:.1f}%)")

                # Check metadata
                metadata = filtered_topo.get('filter_metadata', {})
                if metadata:
                    print(f"  ✓ Filter metadata present")
                    print(f"    - Removed nodes: {metadata.get('removed_nodes', 0)}")
                    print(f"    - Removed edges: {metadata.get('removed_edges', 0)}")
                else:
                    print(f"  ✗ Filter metadata missing")
                    all_passed = False

                # Verify graph consistency
                if filtered_nodes > 0:
                    print(f"  ✓ Filtered graph has nodes")
                else:
                    print(f"  ✗ Filtered graph is empty")
                    all_passed = False

            else:
                print(f"  Note: Filtered topology not generated for this episode")
                print(f"  Run: python filter_topology_by_root_cause.py {episode_data['episode_path']}")

        except Exception as e:
            print(f"❌ Error loading {ep_id}: {e}")
            import traceback
            traceback.print_exc()
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("✓ All tests passed!")
    else:
        print("✗ Some tests failed")

    return all_passed


if __name__ == '__main__':
    success = test_filtered_topology_integration()
    sys.exit(0 if success else 1)
