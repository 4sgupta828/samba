"""
Correlated Noise Generator for Metric Dynamics.

Generates multivariate correlated noise using Cholesky decomposition to model
realistic fluctuations where metrics naturally spike together (e.g., CPU and latency).

Theory:
    Independent noise: Each metric gets independent Gaussian noise.
    Correlated noise: Noise is drawn from multivariate Gaussian with correlation matrix.

Implementation:
    1. Define N×N correlation matrix ρ
    2. Compute Cholesky factorization: L where ρ = L @ L.T
    3. Generate uncorrelated standard normals: z ~ N(0, I)
    4. Transform to correlated: x = L @ z
    5. Scale by metric-specific standard deviations: noise = x * σ
"""

import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple
import numpy as np


@dataclass
class CorrelationConfig:
    """
    Configuration for correlated noise generation.

    Defines correlation structure between 5 metrics:
    - Index 0: CPU
    - Index 1: Memory
    - Index 2: Latency
    - Index 3: Throughput
    - Index 4: Error
    """

    # 5×5 correlation matrix
    # Format: correlations[i][j] = correlation between metric i and metric j
    correlations: List[List[float]] = None

    def __post_init__(self):
        """Initialize with default correlations if none provided."""
        if self.correlations is None:
            # Default realistic correlation structure
            # Order: [CPU, MEM, LAT, TPS, ERR]
            self.correlations = [
                [1.0,  0.3,  0.7, -0.2,  0.5],  # CPU: strong positive with LAT, moderate with ERR
                [0.3,  1.0,  0.2, -0.1,  0.1],  # MEM: weak correlations
                [0.7,  0.2,  1.0, -0.3,  0.8],  # LAT: strong positive with CPU and ERR
                [-0.2, -0.1, -0.3,  1.0, -0.4], # TPS: negative correlations (high load = low TPS under stress)
                [0.5,  0.1,  0.8, -0.4,  1.0],  # ERR: strong positive with LAT
            ]

    def to_numpy(self) -> np.ndarray:
        """Convert correlation matrix to numpy array."""
        return np.array(self.correlations, dtype=np.float64)

    def validate(self) -> Tuple[bool, Optional[str]]:
        """
        Validate the correlation matrix.

        Checks:
        1. Matrix is 5×5
        2. Matrix is symmetric
        3. Diagonal elements are 1.0
        4. All correlations are in [-1, 1]
        5. Matrix is positive semi-definite (via Cholesky decomposition)

        Returns:
            (is_valid, error_message)
        """
        matrix = self.to_numpy()

        # Check shape
        if matrix.shape != (5, 5):
            return False, f"Expected 5×5 matrix, got {matrix.shape}"

        # Check symmetric
        if not np.allclose(matrix, matrix.T):
            return False, "Matrix is not symmetric"

        # Check diagonal
        if not np.allclose(np.diag(matrix), 1.0):
            return False, f"Diagonal must be all 1.0, got {np.diag(matrix)}"

        # Check range
        if np.any(matrix < -1.0) or np.any(matrix > 1.0):
            return False, "Correlations must be in [-1, 1]"

        # Check positive semi-definite via Cholesky
        try:
            np.linalg.cholesky(matrix)
        except np.linalg.LinAlgError:
            return False, "Matrix is not positive semi-definite"

        return True, None


class CorrelatedNoiseGenerator:
    """
    Generates correlated multivariate noise using Cholesky decomposition.

    Usage:
        config = CorrelationConfig()
        generator = CorrelatedNoiseGenerator(config)
        scales = [0.02, 0.02, 0.05, 0.05, 0.1]  # Standard deviations for each metric
        noise = generator.generate(scales, rng)
        # noise[0] = CPU noise, noise[1] = MEM noise, etc.
    """

    def __init__(self, config: Optional[CorrelationConfig] = None):
        """
        Initialize the generator and precompute Cholesky decomposition.

        Args:
            config: Correlation configuration (uses defaults if None)

        Raises:
            ValueError: If correlation matrix is invalid
        """
        self.config = config if config is not None else CorrelationConfig()

        # Validate correlation matrix
        is_valid, error_msg = self.config.validate()
        if not is_valid:
            raise ValueError(f"Invalid correlation matrix: {error_msg}")

        # Precompute Cholesky decomposition
        # ρ = L @ L.T where L is lower triangular
        correlation_matrix = self.config.to_numpy()
        self.cholesky_lower = np.linalg.cholesky(correlation_matrix)

        # Dimensionality (should be 5)
        self.n_metrics = self.cholesky_lower.shape[0]

    def generate(self, scales: List[float], rng: random.Random) -> List[float]:
        """
        Generate a single correlated noise sample.

        Args:
            scales: Standard deviation for each metric (length 5)
            rng: Random number generator for reproducibility

        Returns:
            List of correlated noise values (length 5)

        Raises:
            ValueError: If scales has wrong length
        """
        if len(scales) != self.n_metrics:
            raise ValueError(f"Expected {self.n_metrics} scales, got {len(scales)}")

        # Generate uncorrelated standard normals
        z = np.array([rng.gauss(0, 1) for _ in range(self.n_metrics)])

        # Transform to correlated: x = L @ z
        correlated = self.cholesky_lower @ z

        # Scale by metric-specific standard deviations
        scales_array = np.array(scales)
        noise = correlated * scales_array

        return noise.tolist()

    def generate_batch(
        self,
        scales: List[float],
        n_samples: int,
        rng: random.Random
    ) -> np.ndarray:
        """
        Generate multiple correlated noise samples efficiently.

        Args:
            scales: Standard deviation for each metric (length 5)
            n_samples: Number of samples to generate
            rng: Random number generator for reproducibility

        Returns:
            Array of shape (n_samples, 5) with correlated noise

        Raises:
            ValueError: If scales has wrong length
        """
        if len(scales) != self.n_metrics:
            raise ValueError(f"Expected {self.n_metrics} scales, got {len(scales)}")

        # Generate uncorrelated standard normals: (n_samples, n_metrics)
        z = np.array([[rng.gauss(0, 1) for _ in range(self.n_metrics)] for _ in range(n_samples)])

        # Transform to correlated: X = Z @ L.T (broadcasting over samples)
        # Note: Using L.T for row-wise transformation
        correlated = z @ self.cholesky_lower.T

        # Scale by metric-specific standard deviations
        scales_array = np.array(scales)
        noise = correlated * scales_array

        return noise

    def get_correlation_matrix(self) -> np.ndarray:
        """Get the correlation matrix being used."""
        return self.config.to_numpy()

    def verify_empirical_correlations(
        self,
        scales: List[float],
        n_samples: int = 10000,
        random_seed: Optional[int] = None
    ) -> Tuple[np.ndarray, float]:
        """
        Generate samples and compute empirical correlation matrix to verify correctness.

        Args:
            scales: Standard deviations for each metric
            n_samples: Number of samples to generate for verification
            random_seed: Random seed for reproducibility

        Returns:
            (empirical_correlation_matrix, max_difference)
        """
        rng = random.Random(random_seed)
        samples = self.generate_batch(scales, n_samples, rng)

        # Compute empirical correlation matrix
        # Normalize by standard deviations to get correlations
        normalized_samples = samples / np.array(scales)
        empirical_corr = np.corrcoef(normalized_samples.T)

        # Compute maximum difference from configured matrix
        configured_corr = self.get_correlation_matrix()
        max_diff = np.max(np.abs(empirical_corr - configured_corr))

        return empirical_corr, max_diff


# Convenience functions for common use cases

def create_default_generator() -> CorrelatedNoiseGenerator:
    """Create a generator with default realistic correlations."""
    return CorrelatedNoiseGenerator(CorrelationConfig())


def create_high_correlation_generator() -> CorrelatedNoiseGenerator:
    """Create a generator with high correlations (for stress testing)."""
    config = CorrelationConfig(correlations=[
        [1.0,  0.5,  0.9, -0.4,  0.7],  # CPU
        [0.5,  1.0,  0.5, -0.2,  0.3],  # MEM
        [0.9,  0.5,  1.0, -0.5,  0.9],  # LAT
        [-0.4, -0.2, -0.5,  1.0, -0.6], # TPS
        [0.7,  0.3,  0.9, -0.6,  1.0],  # ERR
    ])
    return CorrelatedNoiseGenerator(config)


def create_independent_generator() -> CorrelatedNoiseGenerator:
    """Create a generator with no correlations (equivalent to independent noise)."""
    config = CorrelationConfig(correlations=[
        [1.0,  0.0,  0.0,  0.0,  0.0],
        [0.0,  1.0,  0.0,  0.0,  0.0],
        [0.0,  0.0,  1.0,  0.0,  0.0],
        [0.0,  0.0,  0.0,  1.0,  0.0],
        [0.0,  0.0,  0.0,  0.0,  1.0],
    ])
    return CorrelatedNoiseGenerator(config)
