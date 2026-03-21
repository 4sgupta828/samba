# Topology bank (LLM-generated architectures)

This folder is **empty by default** in the public repository. Populate it by running:

```bash
python generate_topology_bank.py --samples 2 --output data/topology_bank
```

Requirements:

- `ANTHROPIC_API_KEY` in your environment (see project root `README.md`).

Each generated subdirectory should contain at least:

- `graph.json`
- `semantic_map.json`

**Note:** Procedural dataset generation (`generate_dataset.py` without `--llm-topologies`) does **not** require this folder. The dashboard only needs a populated bank when you enable **LLM topologies** for generation.
