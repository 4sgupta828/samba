# Data Directory

Generated datasets are intentionally not included in the public repository.

Use the scripts below to regenerate data locally:

- `python generate_dataset.py -n 1 -v`
- `python generate_topology_bank.py --output data/topology_bank`

Expected outputs include:

- `data/data_<timestamp>/ep_<n>/...`
- `data/topology_bank/<scenario>_<size>_<idx>/...` (after you run `generate_topology_bank.py`; the empty `data/topology_bank/` folder is kept in git so paths exist)
