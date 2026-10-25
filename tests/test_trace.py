"""Test della registrazione dell'evoluzione (usata dalla visualizzazione dell'algoritmo)."""
import base64
import json

import numpy as np
import pytest

from goalga import GAConfig, run_ga
from goalga.genetic import GAProgress, is_valid
from goalga.trace import EvolutionTrace, sample_individuals, select_frames


def run_with_trace(problem, **cfg):
    trace = EvolutionTrace(n_scenarios=problem.S, n_portfolios=problem.H)
    result = run_ga(problem, GAConfig(pop_size=40, patience=25, seed=5, **cfg), callback=trace)
    return trace, result


def decode(payload, key, shape):
    return np.frombuffer(base64.b64decode(payload[key]), dtype=np.uint8).reshape(shape)


def test_progress_exposes_population_and_scores(small_problem):
    seen = []
    run_ga(small_problem, GAConfig(pop_size=20, patience=3, seed=1), callback=seen.append)
    first = seen[0]
    assert first.population.shape == (20, small_problem.T) and first.scores.shape == (20,)
    assert first.evaluations > 0 and seen[-1].evaluations >= first.evaluations
    assert np.all(is_valid(first.population))


def test_trace_records_every_generation(small_problem):
    trace, result = run_with_trace(small_problem)
    assert trace.n_generations == result.generations
    assert trace.total_evaluations > 0
    # ogni popolazione registrata è ordinata dal migliore al peggiore e rispetta il vincolo di Eq. 2
    for pop in trace._pop:
        assert pop.shape == (40, small_problem.T)
        assert np.all(is_valid(pop))


def test_payload_round_trip_matches_the_result(small_problem):
    trace, result = run_with_trace(small_problem)
    p = trace.payload(max_frames=30, max_individuals=16, elapsed=result.elapsed, stopped_by=result.stopped_by,
                      best_generation=result.best_generation)
    T, F, N = p["T"], p["F"], p["N"]
    assert T == small_problem.T and F <= 32 and N == 16
    assert len(p["gens"]) == len(p["pr"]) == len(p["score"]) == len(p["evals"]) == F
    pop = decode(p, "pop", (F, N, T))
    champ = decode(p, "champ", (F, T))
    assert np.all(is_valid(pop)) and np.all(is_valid(champ))
    assert 1 <= pop.min() and pop.max() <= p["K"]
    # l'ultimo fotogramma è l'ultima generazione e contiene la soluzione finale
    assert p["gens"][0] == 1 and p["gens"][-1] == result.generations
    assert np.array_equal(champ[-1], result.path)
    assert p["pr"][-1] == pytest.approx(result.pr) and p["score"][-1] == pytest.approx(result.score)
    # il miglior punteggio non peggiora mai e le valutazioni sono cumulative
    assert np.all(np.diff(p["score"]) >= -1e-12) and np.all(np.diff(p["evals"]) >= 0)
    assert p["generations"] == result.generations and p["best_generation"] == result.best_generation + 1


def test_payload_is_strict_json(small_problem):
    trace, _ = run_with_trace(small_problem)
    text = json.dumps(trace.payload(), allow_nan=False)
    assert "NaN" not in text and len(text) < 600_000


def test_non_finite_irr_becomes_null():
    trace = EvolutionTrace(n_scenarios=10, n_portfolios=3)
    pop = np.array([[3, 2, 1], [2, 2, 1]])
    trace.record(GAProgress(0, 0.5, 0.5, float("nan"), pop[0], 0, 5, 0.0, 2, population=pop,
                            scores=np.array([0.5, 0.4]), evaluations=2))
    assert trace.payload()["irr"] == [None]


def test_progress_without_population_is_ignored():
    trace = EvolutionTrace()
    trace.record(GAProgress(0, 0.5, 0.5, 0.0, np.array([1, 1]), 0, 5, 0.0, 1))
    assert trace.n_generations == 0
    with pytest.raises(ValueError):
        trace.payload()


def test_frames_are_dense_at_the_start_and_always_include_the_ends():
    scores = np.minimum(np.arange(400) / 80.0, 1.0)            # migliora fino a 80 e poi resta fermo
    idx = select_frames(scores, 100)
    assert idx[0] == 0 and idx[-1] == 399 and idx.size <= 102
    assert np.all(np.diff(idx) > 0)
    assert np.array_equal(idx[:8], np.arange(8))                # all'inizio nessuna generazione viene saltata
    assert np.array_equal(select_frames(np.zeros(10), 100), np.arange(10))


def test_sampling_keeps_the_best_and_spans_the_ranking():
    pos = sample_individuals(100, 60)
    assert pos.size == 60 and pos[0] == 0 and pos[-1] == 99
    assert np.array_equal(pos[:8], np.arange(8))
    assert np.array_equal(sample_individuals(10, 60), np.arange(10))
