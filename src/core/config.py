"""
Configuration loading and validation module.
"""
import yaml
from typing import Dict, Any


def load_config(path: str) -> dict:
    """Loads a YAML configuration file."""
    with open(path, 'r') as f:
        config = yaml.safe_load(f)

    # Validate configuration
    validate_config(config)

    # Load and set error configuration if present
    if 'error_config' in config:
        from error_config import ErrorConfiguration, set_error_config
        error_cfg = ErrorConfiguration.from_dict(config['error_config'])
        set_error_config(error_cfg)
        print(f"Loaded error configuration (inline)")
    elif 'error_config_path' in config:
        # Load error config from external file
        import os
        from error_config import ErrorConfiguration, set_error_config

        error_config_path = config['error_config_path']
        # Make path relative to the working directory if not absolute
        if not os.path.isabs(error_config_path):
            # Path is already relative to project root (where main.py is run from)
            pass

        if not os.path.exists(error_config_path):
            print(f"Warning: Error config file not found at {error_config_path}")
            print(f"Transient errors will be DISABLED. To enable, create config file or set error_config_path to valid file.")
        else:
            with open(error_config_path, 'r') as f:
                error_config_data = yaml.safe_load(f)

            if 'error_config' in error_config_data:
                error_cfg = ErrorConfiguration.from_dict(error_config_data['error_config'])
                set_error_config(error_cfg)
                print(f"Loaded error configuration from {error_config_path}")
            else:
                print(f"Warning: No 'error_config' section found in {error_config_path}")
    else:
        print("Note: No error configuration specified. Transient errors are DISABLED.")
        print("To enable, add 'error_config_path' to your config file.")

    return config


def validate_config(config: Dict[str, Any]) -> None:
    """
    Validates the configuration structure and required fields.

    Raises:
        ValueError: If configuration is invalid
    """
    # Check for required top-level sections
    required_sections = ['simulation', 'infrastructure', 'telemetry', 'workload']
    for section in required_sections:
        if section not in config:
            raise ValueError(f"Missing required configuration section: '{section}'")

    # Validate simulation section
    sim_config = config['simulation']
    if 'duration' not in sim_config:
        raise ValueError("Missing required field: simulation.duration")
    if not isinstance(sim_config['duration'], (int, float)) or sim_config['duration'] <= 0:
        raise ValueError("simulation.duration must be a positive number")

    # Validate infrastructure section
    infra_config = config['infrastructure']
    if 'path' not in infra_config:
        raise ValueError("Missing required field: infrastructure.path")

    # Validate telemetry section
    telemetry_config = config['telemetry']
    if 'exporter' in telemetry_config:
        valid_exporters = ['console', 'otlp', 'file']
        if telemetry_config['exporter'] not in valid_exporters:
            raise ValueError(f"telemetry.exporter must be one of {valid_exporters}")

    # Validate workload section
    workload_config = config['workload']
    if 'path' not in workload_config:
        raise ValueError("Missing required field: workload.path")
