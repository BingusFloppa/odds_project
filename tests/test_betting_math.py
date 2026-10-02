import numpy as np

from odds_analytics.betting_math import (
    biv_poisson_matrix,
    cache_key,
    resolve_asian_hcap,
    resolve_asian_total,
)


def test_cache_key_is_stable():
    assert cache_key(1.5, 3.0, None) == cache_key(1.5, 3.0, None)
    assert cache_key(1.5, 3.0, None) != cache_key(1.51, 3.0, None)


def test_poisson_matrix_normalizes():
    matrix = biv_poisson_matrix(1.2, 0.9, 0.1)
    assert matrix.shape == (10, 10)
    assert np.isclose(matrix.sum(), 1.0)


def test_asian_total_push():
    assert resolve_asian_total(2, 2.0, 2.0, True) == 0.0


def test_asian_hcap_win():
    assert resolve_asian_hcap(1, 0.0, 2.0) == 1.0
