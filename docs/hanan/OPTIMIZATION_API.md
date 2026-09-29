# Optimization API Reference

`hanan.optimization` — sparse Gauss–Newton / Levenberg–Marquardt for problems written as
a weighted sum of squared residuals. Source: `hanan/src/hanan/optimization/`.

## The problem it solves

All unknowns live in one flat vector `X`, split into named blocks (`"v"` for vertex
positions, `"n_f"` for face normals, …). Each objective term `k` contributes a residual
vector `r_k(X)` with weight `w_k`, and the optimizer minimises

```
E(X) = Σ_k  w_k ‖ r_k(X) ‖²
```

Constraints are **soft**: a constraint is just a term with a large weight.

Each iteration linearises every residual, `r_k(X + dx) ≈ r_k + J_k dx`, and solves the
damped normal equations

```
(H + μ I) dx = −b,     H = Σ_k w_k J_kᵀ J_k,     b = Σ_k w_k J_kᵀ r_k
```

with a sparse direct solver. Two step policies (`initialize_optimizer(adaptive_mu=...)`):

| Mode | Behaviour |
|---|---|
| `adaptive_mu=True` (default) | Levenberg–Marquardt with a gain ratio (below). The energy never increases. |
| `adaptive_mu=False` | Fixed small damping `μ = 1e-6 · max(diag H)`; every step is accepted (Gauss–Newton with a tiny regulariser). Used by all L-mesh code. |

**Adaptive steps.** The quadratic model is `m(dx) = Σ_k w_k ‖r_k + J_k dx‖²`; for the step
above it predicts the decrease `m(0) − m(dx) = μ‖dx‖² − bᵀdx`, and the gain ratio is

```
ρ = (E(X) − E(X + dx)) / (μ‖dx‖² − bᵀdx)        (exactly 1 when the residuals are linear)
```

A trial with `ρ > 0` is accepted: μ is divided by 3 if `ρ > 0.75`, doubled if `ρ < 0.25`.
A trial that raises the energy is rejected: μ is multiplied by 4 and the system is solved
again, up to 10 trials per iteration. If all are rejected, `X` stays where it is.

After every step it takes, the optimizer calls `term.accept_step(X)` on each term.

Terms are evaluated in parallel threads (one per active term, capped at the CPU count).
A term whose weight is 0 is skipped entirely.

## Quick start

```python
from hanan.geometry.io import read_obj
from hanan.geometry.mesh import Mesh
from hanan.optimization import Optimizer, Planarity

V, F = read_obj("mesh.obj")
mesh = Mesh(); mesh.make_mesh(V, F)

opt = Optimizer()
opt.add_variable("v", mesh.vertices.flatten())        # 1. declare ALL variable blocks first
opt.add_variable("n_f", mesh.face_normals.flatten())

term = Planarity(); term.name = "Planarity"
opt.add_objective_term(term, args=([mesh.faces]), w=1.0, ce=True)   # 2. then register terms
opt.unitize_variable("n_f", 3, w=5)

opt.initialize_optimizer(adaptive_mu=False)            # 3. reset iteration state
for _ in range(20):
    opt.get_gradients()                                 # assemble H, b and the energies
    opt.optimize_step()                                 # solve and update X

V_new = opt.unpack("v").reshape(-1, 3)
opt.print_report()
```

Order matters: a term sizes its Jacobian from the variable vector when it is registered, so
declare every variable block before adding terms.

`ce=True` records the term's energy in `opt.energy_dic` / the reports; it does not change
the optimization.

## Optimizer

### Variables

| Method | Description |
|---|---|
| `add_variable(var_name, vals)` | Declares a named variable block and sets its initial values |
| `init_variable(name, vals)` | Sets the initial values of a variable block (both X and X0) |
| `unpack()` | Extracts a sub-vector from the variable vector based on the provided variable name(s) |

### Terms and weights

| Method | Description |
|---|---|
| `add_objective_term(term, args, w=1, ce=False)` | Adds an objective term to the optimizer |
| `add_constraint(constraint, args, w=1, ce=False)` | DEPRECATED: Use add_objective_term() instead |
| `get_term_weights_dict()` |  |
| `set_term_weights(weights_dict)` | Sets the weights of objective terms using a dictionary |
| `set_term_weight(name, w)` | Sets the weight of a specific objective term |

### Built-in term shortcuts

| Method | Description |
|---|---|
| `unitize_variable(var_name, dim, w)` | Adds a unit vector constraint to enforce that a variable has unit norm |
| `edge_length(var_name, edges, target_length, w)` | Adds an edge length constraint to enforce specific lengths for edges |
| `set_fairness(var_name, adj_list, dim, damp_factor=0.9, damp_iteration=10, w=0.001, ce=False)` | Adds a fairness constraint to smooth out variations among adjacent vertices |
| `set_lap_smooth(var_name, indices, adj_list, dim, damp_factor=0.9, damp_iteration=10, w=0.001, ce=False)` | Adds a fairness constraint to smooth out variations among adjacent vertices |
| `control_variable(var_name, w)` | Adds a step control constraint that limits the change (step size) of a variable |
| `proximity_reference(var_name, vertices_Reference, faces_Reference, w_proximity, w_gliding)` | Adds a proximity constraint to keep vertices close to a reference mesh.  |

### Solving

| Method | Description |
|---|---|
| `initialize_optimizer(verbose=False, adaptive_mu=True, num_threads=None)` | Resets iteration bookkeeping before starting (or restarting) the optimization loop |
| `get_gradients()` | Computes and accumulates the gradients (Hessian and residual vector) from all objective terms |
| `optimize_step()` | Executes one iteration of the Levenberg–Marquardt method |
| `optimize(max_iter=100, tol=1e-08)` | Runs the optimization loop until convergence or until the maximum number of iterations is reached |

### Results and reports

| Method | Description |
|---|---|
| `get_variables()` | Prints and returns the best variable vector found |
| `get_data_frame_optimization()` | Returns the DataFrame containing optimization iteration data |
| `get_report()` | Returns weights, iterations and energy per constraint as a formatted string |
| `print_report()` | Print weights, iterations and energy per constraint in a formatted table |
| `print_energy_report()` | Prints the energy contributions per constraint |


## Built-in objective terms

Each term lives in its own module, named after the class in snake_case
(`EdgeLength` → `hanan.optimization.edge_length`); all are exported by `hanan.optimization`.
The name a term registers under (`term.name`, the key in `energy_dic` and in weight
dictionaries) is unchanged from earlier versions, e.g. `EdgeLength` registers as `"Edge_Lenght"`.

| Term (module) | Residual per element | Registered with |
|---|---|---|
| `Planarity` | `(v_{i+1} − v_i) · n_f` for consecutive vertices of each face | `add_objective_term(Planarity(), (faces,))`; variables `"v"`, `"n_f"` |
| `Cyclicity` | `(v_{i+1} − v_i) · (m_i − c_f)` and `(m_i − c_f) · n_f`, `m_i` the edge midpoint (quad faces) | `add_objective_term(Cyclicity(), (faces, "v", "cf", "n_f"))` |
| `Unit` | `‖x_i‖² − 1` | `unitize_variable(name, dim, w)` |
| `EdgeLength` | `‖v_j − v_i‖² − ℓ²` (ℓ = current length unless given) | `edge_length(name, edges, target_length, w)` |
| `LaplacianFairness` | `v_i − mean(neighbours)` | `set_fairness` (valence ≠ 4), `set_lap_smooth` |
| `QuadFairness` | `2v_i − v_a − v_c`, `2v_i − v_b − v_d` (opposite neighbours) | `set_fairness` (valence 4) |
| `TargetValue` | `x_i − target_i` | `add_objective_term(TargetValue(), (name, targets))` |
| `FixValueVariable` | `x_i − value_i` for selected indices | `add_objective_term(FixValueVariable(), (name, indices, values))` |
| `StepControl` | `x_i − x_i^{prev}` (proximal: the reference moves to each new iterate) | `control_variable(name, w)` |
| `PrevIterationRegularizer` | `X − X^{prev}` (all variables, proximal) | `add_objective_term(PrevIterationRegularizer(), ())` |
| `Corner` | `cos∠(v_l − c, v_r − c) − cos A` (normalisation lagged one iteration) | `add_objective_term(Corner(), (name, corners, adj, angle))` |
| `ProximityReference` | `v_i − π(v_i)`, `π` = closest point on a reference mesh | `proximity_reference(name, V, F, w_prox, w_glide)` |
| `GlideReference` | `(v_i − π(v_i)) · n_i` (normal lagged one iteration) | same call |

The fairness terms decay their own weight: each iteration multiplies `w` by `damp_factor`,
and after `damp_iteration` iterations the weight becomes 0.

## Writing an objective term

Subclass `ObjectiveTerm` and implement three things:

1. `initialize_objective(X, var_idx, *args)` — runs **once** when the term is registered.
   Read the global indices of your variables from `var_idx[name]`, set
   `self.num_residuals`, and describe the Jacobian's sparsity pattern as parallel arrays
   `self._rows` / `self._cols` (one entry per non-zero, no duplicate `(row, col)` pairs).
2. `res(X)` — the residual vector, length `num_residuals`. Must not modify the term's state:
   the solver also calls it at trial points it may reject.
3. `grad(X)` — the Jacobian **values**, in exactly the order of `_rows` / `_cols`.

Optionally override `accept_step(X)` for state that should follow the iterates (it is called
after every step the optimizer takes; see `StepControl`, a proximal term that keeps each
step close to the previous iterate).

Example: keep points on a sphere of radius `R` around `c`, residual `‖p_i − c‖² − R²`:

```python
import numpy as np
from hanan.optimization import ObjectiveTerm

class OnSphere(ObjectiveTerm):
    def __init__(self):
        super().__init__()
        self.name = "OnSphere"

    def initialize_objective(self, X, var_idx, var_name, center, radius):
        self.idx = var_idx[var_name]                 # global indices, 3 per point
        self.c, self.R2 = np.asarray(center, float), float(radius) ** 2
        self.num_residuals = len(self.idx) // 3
        self._rows = np.arange(self.num_residuals).repeat(3)   # row i has 3 entries
        self._cols = self.idx                                   # x_i, y_i, z_i

    def res(self, X):
        d = X[self.idx].reshape(-1, 3) - self.c
        return np.einsum("ij,ij->i", d, d) - self.R2

    def grad(self, X):
        return (2.0 * (X[self.idx].reshape(-1, 3) - self.c)).ravel()   # d r_i / d p_i
```

```python
opt = Optimizer()
opt.add_variable("p", np.random.default_rng(0).normal(size=30))
opt.add_objective_term(OnSphere(), ("p", [0, 0, 0], 2.0), w=1.0)
opt.initialize_optimizer()
for _ in range(15):
    opt.get_gradients(); opt.optimize_step()
print(np.linalg.norm(opt.unpack("p").reshape(-1, 3), axis=1))   # ≈ 2.0
```

**Constant Jacobians.** If some derivatives never change (linear residuals), put them in
`self._rows_const`, `self._cols_const`, `self._values_const` instead; they are stored once.
Return `None` from `grad` when the whole Jacobian is constant (see `TargetValue`), or only
the varying values when the term has both parts (constant entries come first).

**No hand-written Jacobian.** Set `self.jacobianMethod = "FD"` (central finite differences,
works for any `res`) or `"jax"` (automatic differentiation; `res` must use `jax.numpy`,
and the Jacobian is formed densely, so keep it to small problems). `_rows` / `_cols` are
not needed then.

**Checking a hand-written Jacobian** against finite differences:

```python
from scipy.sparse import coo_matrix
term = OnSphere(); term._initialize_objective(opt.X, opt.var_idx, "p", [0, 0, 0], 2.0)
J = coo_matrix((term.grad(opt.X), (term._rows, term._cols)),
               shape=(term.num_residuals, len(opt.X))).toarray()
J_fd, _ = term.compute_grad_fd(opt.X)
print(abs(J - J_fd.toarray()).max())             # ~1e-9
```

**Legacy style.** Older terms override `compute(X)` returning `(values, residuals)` and
`func(X)` returning the residuals. This still works (the L-conjugacy terms use it); new
terms should use `grad` / `res`.

## Known issues

- `Cyclicity` registers under the name `"Circularity"`; the `EdgeLength` docstring
  describes an inequality although the residual is an equality.
- A `LaplacianFairness` vertex with no neighbours contributes a constant residual (itself).
