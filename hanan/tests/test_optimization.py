"""hanan.optimization — term Jacobians, solver behaviour, and known issues."""

import numpy as np
import pytest
from scipy.sparse import coo_matrix

from hanan.optimization import (
    Cyclicity, EdgeLength, FixValueVariable, LaplacianFairness, ObjectiveTerm, Optimizer,
    Planarity, QuadFairness, StepControl, TargetValue, Unit, GlideReference,
    ProximityReference,
)

N = 4


def _grid(rng):
    xs, ys = np.meshgrid(np.linspace(0, 1, N), np.linspace(0, 1, N))
    V = np.column_stack([xs.ravel(), ys.ravel(), 0.2 * rng.normal(size=N * N)])
    F = [[r * N + c, r * N + c + 1, (r + 1) * N + c + 1, (r + 1) * N + c]
         for r in range(N - 1) for c in range(N - 1)]
    adj = [set() for _ in range(N * N)]
    for f in F:
        for a, b in zip(f, f[1:] + f[:1]):
            adj[a].add(b); adj[b].add(a)
    return V, F, [sorted(a) for a in adj]


def _optimizer(rng, V, F):
    """A leading 'pad' block makes wrong (offset-less) Jacobian columns visible."""
    opt = Optimizer()
    opt.add_variable("pad", rng.normal(size=5))
    opt.add_variable("v", V.ravel())
    opt.add_variable("n_f", rng.normal(size=3 * len(F)))
    opt.add_variable("cf", rng.normal(size=3 * len(F)))
    return opt


def _analytic(term, X):
    values, _ = term._compute(X)
    if values is None:
        values = term._values_const
    elif term._values_const is not None:
        values = np.concatenate([term._values_const, values])
    return coo_matrix((np.asarray(values, float), (term._rows, term._cols)),
                      shape=(term.num_residuals, len(X))).toarray()


def _finite_diff(term, X, h=1e-6):
    J = np.zeros((term.num_residuals, len(X)))
    for i in range(len(X)):
        Xp, Xm = X.copy(), X.copy()
        Xp[i] += h; Xm[i] -= h
        J[:, i] = (term._res_dispatch(Xp) - term._res_dispatch(Xm)) / (2 * h)
    return J


def _cases(V, F, adj):
    inner = [i for i in range(N * N) if len(adj[i]) == 4]
    edges = (np.array([0, 1, 5]), np.array([1, 2, 6]))
    return {
        "Planarity": (Planarity, (F,)),
        "Cyclicity": (Cyclicity, (F, "v", "cf", "n_f")),
        "Unit": (Unit, ("n_f", 3)),
        "EdgeLength": (EdgeLength, ("v", edges, None)),
        "LaplacianFairness": (LaplacianFairness, ("v", list(range(N * N)), adj, 3, 1.0, 10)),
        "QuadFairness": (QuadFairness, ("v", inner, [adj[i] for i in inner], 3, 1.0, 10)),
        "TargetValue": (TargetValue, ("n_f", [0.3])),
        "FixValueVariable": (FixValueVariable, ("v", np.array([0, 4, 7]), [0.5])),
    }


@pytest.mark.parametrize("name", ["Planarity", "Cyclicity", "Unit", "EdgeLength", "LaplacianFairness",
                                  "QuadFairness", "TargetValue", "FixValueVariable"])
def test_jacobian_matches_finite_differences(name):
    rng = np.random.default_rng(0)
    V, F, adj = _grid(rng)
    opt = _optimizer(rng, V, F)
    cls, args = _cases(V, F, adj)[name]
    X = opt.X + 0.05 * rng.normal(size=len(opt.X))
    term = cls(); term._initialize_objective(opt.X, opt.var_idx, *args)
    fresh = cls(); fresh._initialize_objective(opt.X, opt.var_idx, *args)
    J, J_fd = _analytic(term, X), _finite_diff(fresh, X)
    assert np.abs(J - J_fd).max() <= 1e-5 * max(1.0, np.abs(J_fd).max())


@pytest.mark.parametrize("cls", [ProximityReference, GlideReference])
def test_reference_terms_use_the_variable_columns(cls):
    rng = np.random.default_rng(1)
    V, F, _ = _grid(rng)
    opt = _optimizer(rng, V, F)
    tris = np.array([[f[0], f[1], f[2]] for f in F] + [[f[0], f[2], f[3]] for f in F])
    term = cls(); term._initialize_objective(opt.X, opt.var_idx, "v", V + [0, 0, 0.1], tris)
    cols = np.unique(np.nonzero(_analytic(term, opt.X))[1])
    assert set(cols) <= set(opt.var_idx["v"].tolist())


# ── solver ───────────────────────────────────────────────────────────────────

class OnSphere(ObjectiveTerm):
    """The worked example from OPTIMIZATION_API.md ("Writing an objective term")."""

    def __init__(self):
        super().__init__()
        self.name = "OnSphere"

    def initialize_objective(self, X, var_idx, var_name, center, radius):
        self.idx = var_idx[var_name]
        self.c, self.R2 = np.asarray(center, float), float(radius) ** 2
        self.num_residuals = len(self.idx) // 3
        self._rows = np.arange(self.num_residuals).repeat(3)
        self._cols = self.idx

    def res(self, X):
        d = X[self.idx].reshape(-1, 3) - self.c
        return np.einsum("ij,ij->i", d, d) - self.R2

    def grad(self, X):
        return (2.0 * (X[self.idx].reshape(-1, 3) - self.c)).ravel()


@pytest.mark.parametrize("adaptive", [True, False])
def test_custom_term_converges(adaptive):
    opt = Optimizer()
    opt.add_variable("p", np.random.default_rng(0).normal(size=30))
    opt.add_objective_term(OnSphere(), ("p", [0, 0, 0], 2.0), w=1.0)
    opt.initialize_optimizer(adaptive_mu=adaptive)
    for _ in range(20):
        opt.get_gradients(); opt.optimize_step()
    np.testing.assert_allclose(np.linalg.norm(opt.unpack("p").reshape(-1, 3), axis=1), 2.0, atol=1e-8)


def test_weighted_terms_reach_the_weighted_average():
    # minimise w1 (x - a)² + w2 (x - b)²  →  x = (w1 a + w2 b) / (w1 + w2)
    opt = Optimizer()
    opt.add_variable("x", np.zeros(4))
    a, b, w1, w2 = np.array([1.0, 2, 3, 4]), np.array([-1.0, 0, 5, 2]), 1.0, 3.0
    t1, t2 = TargetValue(), TargetValue(); t1.name, t2.name = "a", "b"
    opt.add_objective_term(t1, ("x", a), w=w1)
    opt.add_objective_term(t2, ("x", b), w=w2)
    opt.initialize_optimizer(adaptive_mu=False)
    for _ in range(3):
        opt.get_gradients(); opt.optimize_step()
    np.testing.assert_allclose(opt.unpack("x"), (w1 * a + w2 * b) / (w1 + w2), atol=1e-6)


# ── adaptive Levenberg–Marquardt ─────────────────────────────────────────────

def test_gain_ratio_is_one_on_a_linear_problem():
    # linear residuals: the quadratic model is exact, so ρ = actual / predicted = 1
    opt = Optimizer()
    opt.add_variable("x", np.random.default_rng(2).normal(size=6))
    t = TargetValue(); t.name = "T"
    opt.add_objective_term(t, ("x", np.random.default_rng(3).normal(size=6)), w=2.5)
    opt.initialize_optimizer(adaptive_mu=True)
    opt.get_gradients(); opt.optimize_step()
    assert opt.dataFrameOptimization["Rho"].iloc[-1] == pytest.approx(1.0)


class Rosenbrock(ObjectiveTerm):
    """r = (1 − x, 10 (y − x²)) — the classic curved valley; GN steps overshoot far away."""

    def __init__(self):
        super().__init__()
        self.name = "Rosenbrock"

    def initialize_objective(self, X, var_idx, name):
        self.i = var_idx[name]
        self.num_residuals = 2
        self._rows = np.array([0, 1, 1])
        self._cols = np.array([self.i[0], self.i[0], self.i[1]])

    def res(self, X):
        x, y = X[self.i]
        return np.array([1 - x, 10 * (y - x * x)])

    def grad(self, X):
        x, _ = X[self.i]
        return np.array([-1.0, -20 * x, 10.0])


def _rosenbrock_opt(adaptive=True):
    opt = Optimizer()
    opt.add_variable("p", np.array([-1.2, 1.0]))
    opt.add_objective_term(Rosenbrock(), ("p",), w=1.0)
    opt.initialize_optimizer(adaptive_mu=adaptive)
    return opt


def test_adaptive_energy_never_increases_and_converges():
    opt = _rosenbrock_opt()
    for _ in range(60):
        opt.get_gradients()
        e_before = opt._total_energy
        opt.optimize_step()
        assert opt.energy[-1] <= e_before + 1e-14
    np.testing.assert_allclose(opt.unpack("p"), [1.0, 1.0], atol=1e-6)
    assert opt.energy[opt.bestit] == min(opt.energy)
    np.testing.assert_allclose(opt.bestX, opt.X, atol=1e-12)


def test_rejected_trials_leave_x_untouched_and_raise_mu():
    opt = _rosenbrock_opt()
    opt.get_gradients()
    opt.mu = 1e-3                                # near Gauss–Newton: the first trials overshoot
    X0, E0 = opt.X.copy(), opt._total_energy
    trial_points = []
    orig = opt.evaluate_energy_fast
    opt.evaluate_energy_fast = lambda X, dx: (trial_points.append((X.copy(), dx.copy())), orig(X, dx))[1]
    opt.optimize_step()
    assert len(trial_points) > 1                 # at least one rejection happened
    for X_seen, _ in trial_points:               # every trial was measured from the same X
        np.testing.assert_allclose(X_seen, X0)
    assert opt.mu > 1e-3                         # damping went up after rejections
    assert opt.energy[-1] < E0


def test_all_trials_rejected_keeps_the_point():
    class Up(Rosenbrock):
        """Residual that increases along any step: the model predicts a decrease that never happens."""
        def res(self, X):
            return super().res(X) + 1e3 * np.sum((X[self.i] - np.array([-1.2, 1.0])) ** 2)
    opt = Optimizer()
    opt.add_variable("p", np.array([-1.2, 1.0]))
    opt.add_objective_term(Up(), ("p",), w=1.0)
    opt.initialize_optimizer(adaptive_mu=True)
    opt.get_gradients(); X0, E0 = opt.X.copy(), opt._total_energy
    opt._init_mu(); opt._LM_adaptive(E0, max_trials=2)
    np.testing.assert_allclose(opt.X, X0)
    assert opt.energy[-1] == E0


def test_mu_decreases_after_good_steps():
    opt = Optimizer()
    opt.add_variable("x", np.ones(4))
    t = TargetValue(); t.name = "T"
    opt.add_objective_term(t, ("x", np.zeros(4)), w=1.0)
    opt.initialize_optimizer(adaptive_mu=True)
    opt.get_gradients(); opt.optimize_step()
    mu1 = opt.mu
    opt.get_gradients(); opt.optimize_step()
    assert opt.mu < mu1                          # ρ = 1 > 0.75 → μ / 3


def test_optimize_return_value():
    assert _rosenbrock_opt().optimize(max_iter=200, tol=1e-12) is True
    assert _rosenbrock_opt().optimize(max_iter=2, tol=1e-12) is False
    stopped = _rosenbrock_opt(); stopped.stop = True
    assert stopped.optimize(max_iter=50) is False


# ── terms that track the previous iterate ────────────────────────────────────

def test_step_control_residual_is_pure_and_follows_accepted_steps():
    opt = Optimizer(); opt.add_variable("x", np.zeros(3))
    t = StepControl(); t._initialize_objective(opt.X, opt.var_idx, "x")
    X = np.array([0.5, 0.0, 0.0])
    np.testing.assert_allclose(t.res(X), t.res(X))          # no side effects
    t.accept_step(X)
    np.testing.assert_allclose(t.res(X), 0.0)


def test_step_control_acts_as_a_proximal_term():
    # target 0 with weight 1 plus step control with weight 1 on x:
    # each step solves min (x-0)² + (x - x_k)²  →  x_{k+1} = x_k / 2
    opt = Optimizer()
    opt.add_variable("x", np.array([8.0]))
    t = TargetValue(); t.name = "T"
    opt.add_objective_term(t, ("x", np.zeros(1)), w=1.0)
    opt.control_variable("x", w=1.0)
    opt.initialize_optimizer(adaptive_mu=False)
    xs = []
    for _ in range(3):
        opt.get_gradients(); opt.optimize_step(); xs.append(float(opt.unpack("x")[0]))
    np.testing.assert_allclose(xs, [4.0, 2.0, 1.0], rtol=1e-5)
