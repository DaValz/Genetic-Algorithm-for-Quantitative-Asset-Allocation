"""Test del modulo di compatibilità con la vecchia API."""
import numpy as np
import pandas as pd
import pytest

from goalga.genetic import is_valid


def test_legacy_api_still_works(market):
    import ga_model

    hist = pd.DataFrame(market.history)  # 9 colonne: un portafoglio ciascuna
    calls = []
    with pytest.warns(DeprecationWarning):
        ga = ga_model.GoalBasedGA(hist, 100_000, 5_000, {10: 80_000, 20: 300_000}, time_horizon=20,
                                  pop_size=40, max_generations=15, seed=3)
    path, (pr, irr) = ga.run(progress_callback=lambda *args: calls.append(args))
    assert len(path) == 20 and is_valid(path) and 0.0 <= pr <= 1.0 and np.isfinite(irr)
    assert len(calls) == 15 and len(calls[0]) == 5


def test_legacy_api_validates_columns():
    import ga_model

    with pytest.warns(DeprecationWarning), pytest.raises(ValueError):
        ga_model.GoalBasedGA(pd.DataFrame(np.zeros((10, 3))), 1, 1, {5: 1}, time_horizon=10)
