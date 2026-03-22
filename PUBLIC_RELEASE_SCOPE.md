# Public Release Scope

This repository is published as **Dataraft** — a microservice simulation and whitebox RCA framework.

## In Scope

- Simulation engine and generation flow:
  - `src/`
  - `config/`
  - `generate_dataset.py`
  - `batch_generate_datasets.py`
- Whitebox RCA framework:
  - `analysis2/run_rca_batch.py`
  - `analysis2/whitebox_rca.py`
  - dependent modules in `analysis2/` used by runtime
- UI paths:
  - `viz/` dashboard UI
  - simulation runtime path driven by `src/simulation.py`
- Offline topology generation:
  - `generate_topology_bank.py`
  - `topology_bank/` assets (when used)
  - optional topology filtering scripts

## Archived Internal/Legacy Artifacts

The following files were conservatively moved to `archive/internal_legacy/`:

- AWS operational scripts and notes:
  - `archive/internal_legacy/aws_ops/`
- Internal analysis docs and backups:
  - `archive/internal_legacy/analysis2_docs/`
  - `archive/internal_legacy/analysis2_debug/`
- Scratch IDE project:
  - `archive/internal_legacy/untitled/`
- Strict runtime cleanup pass:
  - `archive/internal_legacy/strict_runtime_pass2/root_files/`
  - `archive/internal_legacy/strict_runtime_pass2/root_dirs/`
  - `archive/internal_legacy/strict_runtime_pass2/analysis2/`
- Analysis dead code (not imported by dataset generation or dashboard):
  - `archive/internal_legacy/analysis_pruned_dead/` (legacy forensic pipeline, SOTA analyzer package, unused viz chart)

## Removed Local Artifacts

- Local IDE metadata under `.idea/`

## Minimal Quickstart

```bash
# Install dependencies
pip install -r requirements.txt

# Run simulation dataset generation
python generate_dataset.py -n 1 -v

# Run whitebox RCA on a generated dataset directory
python analysis2/run_rca_batch.py data/data_<timestamp>

# Run dashboard UI
cd viz
python app.py
```

## Notes

- **Topology bank:** use `generate_topology_bank.py` to populate `data/topology_bank/`. If your repo includes a **procedural** mode, no API key is needed; **LLM** topology modes require `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY` can be used by optional LLM-assisted analysis paths in dataset generation
- Generated datasets and large topology-bank artifacts are typically **gitignored**; regenerate locally after clone
