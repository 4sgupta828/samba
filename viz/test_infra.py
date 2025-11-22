#!/usr/bin/env python3
"""Test script to check infra context."""

from data_loader import load_episode
import json

episode_data = load_episode('ep_0', '../data/final_validation')
infra = episode_data['infra_context']

# Sample relationships
print('Sample relationships (first 50):')
for i, rel in enumerate(infra['architecture']['relationships'][:50]):
    print(f'{i}: {rel["source"]} -> {rel["target"]} ({rel["type"]})')

print('\n\nComponents summary:')
component_types = {}
for comp in infra['architecture']['components']:
    comp_type = comp['type']
    component_types[comp_type] = component_types.get(comp_type, 0) + 1

for comp_type, count in sorted(component_types.items()):
    print(f'{comp_type}: {count}')

# Check message queue relationships specifically
print('\n\nMessage Queue relationships:')
for rel in infra['architecture']['relationships']:
    if 'queue' in rel['source'] or 'queue' in rel['target']:
        print(f'{rel["source"]} -> {rel["target"]} ({rel["type"]})')
