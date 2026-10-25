"""Test dell'algoritmo genetico: operatori, convergenza, determinismo."""
import itertools

import numpy as np
import pytest

from goalga import GAConfig, run_ga
from goalga.genetic import (
    apply_gene_mutation, crossover, is_valid, mutate, random_population, tournament,
)


# ------------------------------------------------------------------ operatori
def test_paper_mutation_example():
    """Esempio a pag. 40 del paper: 8 8 7 7 7 3 2 1, quinto gene +1."""
    out = apply_gene_mutation(np.array([[8, 8, 7, 7, 7, 3, 2, 1]]), np.array([4]), np.array([8]))
    assert out.tolist() == [[8, 8, 8, 8, 8, 3, 2, 1]]


def test_mutation_downwards_lowers_successors():
    out = apply_gene_mutation(np.array([[8, 8, 7, 7, 7, 3, 2, 1]]), np.array([2]), np.array([5]))
    assert out.tolist() == [[8, 8, 5, 5, 5, 3, 2, 1]]


def test_paper_crossover_example_validity():
    """Esempio a pag. 39: solo il primo figlio rispetta il vincolo."""
    p1 = np.array([8, 8, 8, 7, 7, 7, 5, 5])
    p2 = np.array([9, 9, 9, 4, 4, 3, 2, 1])
    c1 = np.concatenate([p1[:5], p2[5:]])
    c2 = np.concatenate([p2[:5], p1[5:]])
    assert c1.tolist() == [8, 8, 8, 7, 7, 3, 2, 1] and is_valid(c1)
    assert c2.tolist() == [9, 9, 9, 4, 4, 7, 5, 5] and not is_valid(c2)


@pytest.mark.parametrize("T,H", [(5, 9), (30, 9), (50, 9), (12, 3)])
def test_all_operators_preserve_the_constraint(T, H):
    rng = np.random.default_rng(0)
    pop = random_population(rng, 400, T, H)
    assert is_valid(pop).all() and pop.min() >= 1 and pop.max() <= H
    scores = rng.random(400)
    for _ in range(50):
        pool = pop[tournament(rng, scores, 400)]
        kids = crossover(rng, pool, 0.55, 400)
        assert kids.shape == (400, T) and is_valid(kids).all()
        pop = mutate(rng, kids, 0.30, 2, H)
        assert is_valid(pop).all() and pop.min() >= 1 and pop.max() <= H


def test_mutation_can_raise_and_lower_risk():
    """La vecchia riparazione annullava ogni mutazione al rialzo (e trascinava giù la coda)."""
    rng = np.random.default_rng(5)
    pop = random_population(rng, 3000, 30, 9)
    mutated = mutate(rng, pop, 1.0, 2, 9)
    delta = mutated.sum(axis=1) - pop.sum(axis=1)
    up, down = (delta > 0).sum(), (delta < 0).sum()
    assert up > 0.2 * (up + down) and down > 0.2 * (up + down)


def test_mutation_never_applies_zero_step():
    rng = np.random.default_rng(1)
    pop = np.full((2000, 20), 5)
    mutated = mutate(rng, pop, 1.0, 2, 9)
    assert (mutated != pop).any(axis=1).all()


def test_initial_population_is_diverse():
    """Il vecchio generatore produceva solo glide path 9 -> 1 (nessun individuo con media <=3 o >=7)."""
    rng = np.random.default_rng(2)
    pop = random_population(rng, 1000, 50, 9)
    means = pop.mean(axis=1)
    assert (means <= 3).mean() > 0.10 and (means >= 7).mean() > 0.10
    assert len(set(map(tuple, pop))) > 500


def test_tournament_uses_replacement_and_prefers_better():
    rng = np.random.default_rng(0)
    scores = np.arange(100, dtype=float)
    winners = tournament(rng, scores, 20_000)
    assert scores[winners].mean() > 60  # pressione selettiva
    assert winners.max() <= 99 and winners.min() >= 0


# ------------------------------------------------------------------ convergenza
def test_ga_finds_the_exhaustive_optimum(small_problem):
    """Su un problema piccolo il GA deve raggiungere l'ottimo trovato con ricerca esaustiva."""
    T, H = small_problem.T, small_problem.H
    candidates = np.array(list(itertools.combinations_with_replacement(range(H, 0, -1), T)))
    assert is_valid(candidates).all()
    best_score = small_problem.evaluate(candidates).score.max()
    result = run_ga(small_problem, GAConfig(pop_size=100, patience=60, seed=11))
    assert result.score == pytest.approx(best_score, abs=1e-9)
    assert is_valid(result.path)


def test_ga_is_deterministic_for_a_given_seed(small_problem):
    cfg = GAConfig(pop_size=50, patience=15, max_generations=100, seed=99)
    a, b = run_ga(small_problem, cfg), run_ga(small_problem, cfg)
    assert a.path.tolist() == b.path.tolist() and a.score == b.score
    c = run_ga(small_problem, GAConfig(pop_size=50, patience=15, max_generations=100, seed=100))
    assert c.history["best_score"].size > 0


def test_patience_termination(small_problem):
    result = run_ga(small_problem, GAConfig(pop_size=40, patience=10, max_generations=500, seed=1))
    assert result.stopped_by == "patience"
    assert result.generations == result.best_generation + 10 + 1


def test_max_generations_cap(small_problem):
    result = run_ga(small_problem, GAConfig(pop_size=20, patience=10_000, max_generations=7, seed=1))
    assert result.generations == 7 and result.stopped_by == "max_generations"


def test_best_score_history_is_monotone(small_problem):
    result = run_ga(small_problem, GAConfig(pop_size=40, patience=30, seed=3))
    assert np.all(np.diff(result.history["best_score"]) >= 0)


def test_user_can_stop_the_run(small_problem):
    calls = []
    result = run_ga(small_problem, GAConfig(pop_size=20, patience=1000, seed=1),
                    callback=lambda p: calls.append(p.generation), should_stop=lambda: len(calls) >= 4)
    assert result.stopped_by == "user" and result.generations == 4


def test_invalid_config_is_rejected(small_problem):
    with pytest.raises(ValueError):
        run_ga(small_problem, GAConfig(pop_size=2))
    with pytest.raises(ValueError):
        run_ga(small_problem, GAConfig(p_m=1.5))
    with pytest.raises(ValueError):
        run_ga(small_problem, GAConfig(elitism=100))
