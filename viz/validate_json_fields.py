"""
Validate that all fields accessed by the UI are present in JSON files.
"""

import json
import os
import sys

def check_label_json(label_path):
    """Check if all required fields are present in label.json"""

    with open(label_path, 'r') as f:
        label = json.load(f)

    # Fields accessed with direct bracket notation in app.py and charts
    required_fields = {
        'episode': 'app.py:60',
        'level': 'app.py:65',
        'scenario': 'app.py:66',
        'root_cause_node': 'app.py:73, component_drilldown.py:640',
        'root_cause_role': 'app.py:75',
        'fault_type': 'app.py:79',
        'fault_start_time': 'app.py:86',
        'topology': 'app.py:94-97, topology.py:195-196',
    }

    # Optional fields (accessed with .get())
    optional_fields = {
        'fault_duration': 'Has fallback to fault_total_duration',
        'fault_total_duration': 'New field name',
    }

    missing_fields = []
    present_fields = []

    print("=" * 70)
    print(f"Validating: {label_path}")
    print("=" * 70)

    # Check required fields
    print("\n✓ REQUIRED FIELDS:")
    for field, location in required_fields.items():
        if field in label:
            present_fields.append(field)
            if field == 'topology':
                # Check nested topology fields
                topology_fields = ['nodes', 'edges', 'frontends']
                for tf in topology_fields:
                    if tf in label['topology']:
                        print(f"  ✓ {field}.{tf} = {label['topology'][tf]}")
                    else:
                        print(f"  ✗ {field}.{tf} - MISSING!")
                        missing_fields.append(f"{field}.{tf}")
            else:
                print(f"  ✓ {field} = {label[field]}")
        else:
            print(f"  ✗ {field} - MISSING! (used in {location})")
            missing_fields.append(field)

    # Check optional fields
    print("\n⚠ OPTIONAL FIELDS (with fallback):")
    for field, note in optional_fields.items():
        if field in label:
            print(f"  ✓ {field} = {label[field]} ({note})")
        else:
            print(f"  - {field} - not present ({note})")

    # Show all available fields
    print("\n📋 ALL AVAILABLE FIELDS IN label.json:")
    for key in sorted(label.keys()):
        if isinstance(label[key], dict):
            print(f"  • {key}: {{{', '.join(label[key].keys())}}}")
        elif isinstance(label[key], list):
            print(f"  • {key}: [{len(label[key])} items]")
        else:
            print(f"  • {key}: {label[key]}")

    # Summary
    print("\n" + "=" * 70)
    if missing_fields:
        print(f"❌ VALIDATION FAILED - {len(missing_fields)} missing field(s):")
        for field in missing_fields:
            print(f"   - {field}")
        return False
    else:
        print(f"✅ VALIDATION PASSED - All {len(required_fields)} required fields present")
        return True


if __name__ == '__main__':
    # Find ep_0 directory
    base_dir = '../data' if len(sys.argv) < 2 else sys.argv[1]

    # Find the most recent data run
    import glob
    data_runs = sorted(glob.glob(os.path.join(base_dir, 'data_*')))

    if not data_runs:
        print(f"No data runs found in {base_dir}")
        sys.exit(1)

    most_recent = data_runs[-1]
    label_path = os.path.join(most_recent, 'ep_0', 'label.json')

    if not os.path.exists(label_path):
        print(f"label.json not found at {label_path}")
        sys.exit(1)

    success = check_label_json(label_path)
    sys.exit(0 if success else 1)
