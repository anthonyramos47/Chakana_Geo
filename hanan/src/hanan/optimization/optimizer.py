import numpy as np
import time as tm
import pandas as pd
from hanan.optimization.unit import Unit
from hanan.optimization.step_control import StepControl
from hanan.optimization.quad_fairness import QuadFairness
from hanan.optimization.laplacian_fairness import LaplacianFairness
from hanan.optimization.edge_length import EdgeLength
from hanan.optimization.proximity_reference import ProximityReference
from hanan.optimization.glide_reference import GlideReference

from scipy.sparse import eye, issparse, diags
from scipy.sparse.linalg import spsolve
from concurrent.futures import ThreadPoolExecutor
import os



class Optimizer():
    def __init__(self) -> None:
        """
        Optimizer for solving non-linear least squares problems using either
        Levenberg–Marquardt (LM) or Projected Gauss–Newton (PG) methods.
        
        The optimization problem is formulated as:
            J^T J dx = - J^T r (for LM)
        or, in the case of PG (to be implemented),
            J^T J (X + λ I) = J^T (X) - r dx.
        
        Attributes:
            X (np.ndarray): The current variable vector.
            X0 (np.ndarray): The initial variable vector.
            var_idx (dict): A dictionary mapping variable names to their indices.
            var (int): Total number of variables.
            bestX (np.ndarray): The best solution found.
            bestit (int): The iteration number of the best solution.
            H (sparse matrix): The Hessian matrix (J^T * J).
            b (np.ndarray): The right-hand side vector (J^T * r).
            it (int): Current iteration count.
            step (float): Step size used in variable updates.
            prevdx (float): Norm of the previous update step.
            method (str): Optimization method ("LM" or "PG").
            energy (list): List of energy (cost) values per iteration.
            energy_dic (dict): Energy contribution per objective term.
            norm_energy_dic (dict): Normalized energy per objective term.
            objective terms (dict): Dictionary of objective term objects.
            verbose (bool): Flag to print progress messages.
            stop (bool): Flag to indicate early termination.
        """
        # Variables and their indices
        self.X = None
        self.X0 = None
        self.var_idx = {}  # Dictionary mapping variable names to indices (e.g. "v1": np.arange(...))
        self.var = 0       # Total number of variables
        
        # Best solution found during optimization
        self.bestX = None
        self.bestit = None
        
        # Hessian and gradient-related objects
        self.H = None
        self.b = None
        self.mu = None  # Damping factor for LM
        self.adaptive_mu = True  # Flag to enable/disable adaptive damping
        self._fixed_idx = None  # Global indices held constant (see fix_variables)
        self._total_energy = 0.0  # Total energy across ALL terms (computed in get_gradients)
        
        # Iteration details and step size
        self.it = None
        self.step = None
        self.prevdx = None
        self.iter_time = []
        self.dataFrameOptimization = pd.DataFrame()
        
        # Optimization method ("LM" for Levenberg–Marquardt or "PG" for Projected Gauss–Newton)
        self.method = None
        
        # Energy history and objective term energy breakdown
        self.energy = []
        self.energy_dic = {}
        self.norm_energy_dic = {}

        # Objective terms registered with the optimizer
        self.objective_terms = {}
        self.constraints = self.objective_terms  # Backward compatibility alias
        
        # Flags for verbosity and stopping the optimization
        self.verbose = False
        self.stop = False

        # Parallelism
        self.num_threads = 1
        self._executor = None

        # Log string for recording optimization progress
        self.log = ""

    def add_variable(self, var_name: str, vals: np.ndarray) -> None:
        """
        Declares a named variable block and sets its initial values.
        The size of the block is inferred from len(vals).

        Args:
            var_name (str): The name of the variable.
            vals (np.ndarray): Initial values; their length defines the block size.
        """
        vals = np.asarray(vals, dtype=float).ravel()
        dim  = len(vals)

        old_var = self.var
        self.var_idx[var_name] = np.arange(old_var, old_var + dim)
        self.var += dim

        # Grow X while preserving previously set values.
        new_X  = np.zeros(self.var)
        new_X0 = np.zeros(self.var)
        if self.X is not None and old_var > 0:
            new_X[:old_var]  = self.X[:old_var]
            new_X0[:old_var] = self.X0[:old_var]
        self.X  = new_X
        self.X0 = new_X0
        self.X[self.var_idx[var_name]]  = vals
        self.X0[self.var_idx[var_name]] = vals

    def init_variable(self, name: str, vals: np.ndarray) -> None:
        """
        Sets the initial values of a variable block (both X and X0).
        Kept for backward compatibility — prefer passing vals to add_variable.
        """
        self.X[self.var_idx[name]]  = vals
        self.X0[self.var_idx[name]] = vals

    def add_objective_term(self, term, args, w: float = 1, ce: bool = False) -> None:
        """
        Adds an objective term to the optimizer.

        Args:
            term: An instance of an ObjectiveTerm subclass.
            args: Additional arguments for the term's initialization.
            w (float): Weight factor for the term.
            ce (bool): If True, the energy from this term is recorded.
        """
        term.consider_energy = ce
        # Initialize term with the current variables and indices.
        term._initialize_objective(self.X, self.var_idx, *args)
        term.set_weigth(w)
        self.objective_terms[term.name] = term
        self.constraints = self.objective_terms  # Keep alias in sync

    def add_constraint(self, constraint, args, w: float = 1, ce: bool = False) -> None:
        """
        DEPRECATED: Use add_objective_term() instead.
        Adds an objective term to the optimizer.

        Args:
            constraint: An instance of an ObjectiveTerm subclass.
            args: Additional arguments for the term's initialization.
            w (float): Weight factor for the term.
            ce (bool): If True, the energy from this term is recorded.
        """
        self.add_objective_term(constraint, args, w, ce)

    def get_term_weights_dict(self) -> dict:
        return dict([(key, term.w) for key, term in self.objective_terms.items()])


    def set_term_weights(self, weights_dict: dict) -> None:
        """
        Sets the weights of objective terms using a dictionary.

        Args:
            weights_dict (dict): Dictionary mapping term names to their new weights.
        """
        changed = False
        for name, w in weights_dict.items():
            if name in self.objective_terms and self.objective_terms[name].w != w:
                changed = True
                self.objective_terms[name].set_weigth(w)

        # Keep track of updated weights
        if changed:
            self.log += f"Updated weights at it {self.it}:\n"
            for name, w in weights_dict.items():
                self.log += f"  {name}: {w}\n" 
        

    def set_term_weight(self, name: str, w: float) -> None:
        """
        Sets the weight of a specific objective term.

        Args:
            name (str): The name of the objective term.
            w (float): The new weight for the term.
        """
        if name in self.objective_terms:
            self.objective_terms[name].set_weigth(w)

    def initialize_optimizer(self, verbose: bool = False, adaptive_mu: bool = True, num_threads: int = None) -> None:
        """
        Resets iteration bookkeeping before starting (or restarting) the optimization loop.

        Call this after all variables have been declared with add_variable() and
        their initial values have been set with init_variable(). It does NOT
        touch X so variable values are preserved.

        Typical setup order:
            1. opt.add_variable("v", n*3)       # declare all variable blocks
            2. opt.init_variable("v", v0)        # set initial values
            3. opt.add_objective_term(...)        # register energy terms
            4. opt.initialize_optimizer(...)      # reset iteration state — call last
            5. opt.optimize(...)

        Args:
            verbose (bool): Print per-iteration energy if True.
            adaptive_mu (bool): Use gain-ratio adaptive damping (recommended).
                                Set False for the simpler fixed-damping LM variant.
        """
        self.it = 0
        self.verbose = verbose
        self.adaptive_mu = adaptive_mu
        self.stop = False
        self.energy = []
        self.energy_dic = {}
        self.norm_energy_dic = {}
        self.bestX = None
        self.bestit = None
        self.prevdx = None
        self.mu = None
        self._total_energy = 0.0
        self.eye = eye(n=self.var, m=self.var, format='csr')

        # Auto-size thread pool: cap at min(active terms, cpu cores)
        active_terms = sum(1 for t in self.objective_terms.values() if not np.isclose(t.w, 0))
        cpus = os.cpu_count() or 1
        if num_threads is None:
            num_threads = min(active_terms, cpus)
        self.num_threads = num_threads
        if self._executor is not None:
            self._executor.shutdown(wait=False)
        self._executor = ThreadPoolExecutor(max_workers=num_threads) if num_threads > 1 else None
        if self.verbose:
            print(f"Thread pool: {num_threads} workers (terms={active_terms}, cpus={cpus})")

    # ------------------------ Optimization Methods ------------------------

    def get_gradients(self) -> None:
        """
        Computes and accumulates the gradients (Hessian and residual vector) from all objective terms.

        When num_threads > 1, each term's _computeGrad runs in a separate thread.
        numpy/scipy release the GIL during heavy linear algebra so threads run
        in parallel. Results are collected and summed on the main thread.
        """
        self.H = None
        self.b = None
        self._total_energy = 0.0

        active_terms = [(name, term) for name, term in self.objective_terms.items()
                        if not np.isclose(term.w, 0)]

        if self._executor is not None and len(active_terms) > 1:
            # Parallel: submit all terms, collect futures
            X = self.X  # local ref — read-only during gradient computation
            futures = {name: self._executor.submit(term._computeGrad, X)
                       for name, term in active_terms}

            for name, term in active_terms:
                H, b, res, meanRes = futures[name].result()
                if self.H is None:
                    self.H, self.b = H, b
                else:
                    try:
                        self.H += H
                        self.b += b
                    except ValueError as e:
                        raise ValueError(
                            f"Shape mismatch accumulating term '{term.name}' (key='{name}'): "
                            f"H_accum={self.H.shape}, H_term={H.shape}. "
                            f"Original error: {e}"
                        ) from e
                self._total_energy += res
                if term.name is not None and term.consider_energy:
                    self.energy_dic[term.name] = res
                    self.norm_energy_dic[term.name] = meanRes
        else:
            # Sequential fallback
            for name, term in active_terms:
                H, b, res, meanRes = term._computeGrad(self.X)
                if self.H is None:
                    self.H, self.b = H, b
                else:
                    try:
                        self.H += H
                        self.b += b
                    except ValueError as e:
                        raise ValueError(
                            f"Shape mismatch accumulating term '{term.name}' (key='{name}'): "
                            f"H_accum={self.H.shape}, H_term={H.shape}. "
                            f"Original error: {e}"
                        ) from e
                self._total_energy += res
                if term.name is not None and term.consider_energy:
                    self.energy_dic[term.name] = res
                    self.norm_energy_dic[term.name] = meanRes
    

    def evaluate_energy_fast(self, X, dx) -> float:
        """
        Fast energy evaluation using residuals computed at X+dx.
        Avoids recomputing constraint Jacobians.

        Args:
            X (np.ndarray): Current variable vector.
            dx (np.ndarray): Step direction.

        Returns:
            float: The total energy at X+dx.
        """
        total_energy = 0.0
        X_trial = X + dx
        for term in self.objective_terms.values():
            if not np.isclose(term.w, 0):
                r = term._res_dispatch(X_trial)
                total_energy += term.w * np.sum(r**2)
        return total_energy
    
    def _init_mu(self) -> None:
        """
        Initializes the damping parameter mu based on the Hessian diagonal.

        Uses tau * max(diag(H)) where tau = 1e-6 as initial damping.
        This follows the standard LM initialization strategy.
        """
        if self.mu is None:
            if issparse(self.H):
                diag_vals = np.abs(self.H.diagonal())
                diag_max = diag_vals.max() if diag_vals.size > 0 else 1.0
            else:
                diag_max = np.abs(np.diag(self.H)).max()
            # Ensure mu is never zero or negative
            self.mu = 1e-6 * max(diag_max, 1.0)

    def fix_variables(self, var_name: str, indices=None, dim: int = 1) -> None:
        """Hold entries of a variable constant for the rest of the optimization.

        A hard constraint, not a penalty: the fixed entries get exactly zero
        step, whatever the energies ask for. Use it for things that must not
        move at all — boundary vertices of a patch, or a block of variables
        during a warm-up phase.

        Args:
            var_name: Name of the variable, as passed to add_variable.
            indices:  Which ELEMENTS of it to fix, in the variable's own
                      numbering (e.g. vertex ids for "v"). None fixes all of it.
            dim:      Components per element; 3 for a variable holding
                      3-vectors, so index k covers entries 3k, 3k+1, 3k+2.

        Implementation: the columns of J belonging to a fixed variable should
        vanish, so row and column i of H = J^T J vanish with them and b_i = 0.
        Rather than touching every term's J, the equivalent mask is applied to
        the ASSEMBLED system in _solve_damped_system, which also leaves the
        per-term CSR caching alone. A unit diagonal is written at the fixed
        rows so dx = 0 there exactly, independent of the LM damping, and the
        matrix keeps a sane condition number.
        """
        if self.var_idx is None or var_name not in self.var_idx:
            raise KeyError(
                f"unknown variable {var_name!r}; add_variable it first "
                f"(have: {sorted(self.var_idx) if self.var_idx else []})")
        idx = np.asarray(self.var_idx[var_name]).ravel()

        if indices is None:
            fixed = idx
        else:
            e = np.asarray(indices, dtype=np.int64).ravel()
            if dim == 1:
                cols = e
            else:
                cols = (dim * e[:, None] + np.arange(dim)).ravel()
            if cols.size and (cols.min() < 0 or cols.max() >= len(idx)):
                raise IndexError(
                    f"index out of range for {var_name!r}: it has {len(idx)} "
                    f"entries ({len(idx)//dim} elements at dim={dim})")
            fixed = idx[cols]

        self._fixed_idx = (fixed if self._fixed_idx is None
                           else np.union1d(self._fixed_idx, fixed))

    def free_variables(self) -> None:
        """Release everything previously passed to fix_variables."""
        self._fixed_idx = None

    def _apply_fixed(self, H, b):
        """Zero the rows/cols of the fixed variables, unit diagonal, b = 0."""
        if self._fixed_idx is None or len(self._fixed_idx) == 0:
            return H, b
        n = H.shape[0]
        keep = np.ones(n)
        keep[self._fixed_idx] = 0.0
        D = diags(keep)
        # D H D zeros row i and column i for every fixed i; the second term
        # puts 1 back on those diagonals so the solve returns dx_i = 0.
        H = D @ H @ D + diags(1.0 - keep)
        return H, b * keep

    def _solve_damped_system(self) -> np.ndarray:
        """
        Solves the damped linear system: (H + μI) dx = -b

        Returns:
            np.ndarray: The computed step direction dx.
        """
        if issparse(self.H):
            H_damped = self.H.copy()
            H_damped.setdiag(H_damped.diagonal() + self.mu)
        else:
            H_damped = self.H.copy()
            H_damped.flat[::self.var + 1] += self.mu

        # After damping, so mu is still derived from the true Hessian.
        H_damped, rhs = self._apply_fixed(H_damped, -self.b)
        return spsolve(H_damped, rhs)

    def _LM_simple(self) -> tuple:
        """
        Simple LM step without adaptive damping (always accepts step).

        Records pre-step energy (from _total_energy computed in get_gradients,
        zero extra cost). bestX is saved before stepping so it matches the
        recorded energy — energy[i] = E(X_i) and bestX achieves energy[bestit].

        Returns:
            tuple: (dx, energy, rho) where rho is None for simple mode.
        """
        dx = self._solve_damped_system()
        energy = self._total_energy  # E(X) before step — already computed, free

        # Track best solution at X (before step), so bestX matches its energy
        if self.it == 0 or energy < (self.energy[self.bestit] if self.bestit is not None else np.inf):
            self.bestX = self.X.copy()
            self.bestit = self.it

        self._take_step(dx)
        self.energy.append(energy)

        return dx, energy, None

    def _take_step(self, dx: np.ndarray) -> None:
        """Move X by dx and let terms that track the previous iterate update it."""
        self.X += dx
        self.prevdx = np.linalg.norm(dx)
        for term in self.objective_terms.values():
            term.accept_step(self.X)

    def _LM_adaptive(self, energy_old: float, max_trials: int = 10) -> tuple:
        """
        Adaptive LM step with step acceptance/rejection based on the gain ratio.

        For E(X) = Σ w‖r‖² the quadratic model is m(dx) = ‖r + J dx‖²_w, so for the
        step solving (H + μI) dx = −b the predicted reduction is
            m(0) − m(dx) = μ‖dx‖² − bᵀdx      (> 0 whenever dx ≠ 0)
        and ρ = (E(X) − E(X + dx)) / (μ‖dx‖² − bᵀdx), which is exactly 1 for linear
        residuals.

        A step is accepted only if it lowers the energy (ρ > 0). Accepted steps
        shrink μ when ρ > 0.75 and grow it when ρ < 0.25; rejected trials multiply
        μ by 4 and re-solve. If all max_trials trials are rejected, X is left
        unchanged (no progress is possible at this damping).

        Args:
            energy_old: Energy before the step.
            max_trials: Maximum number of trials with increased damping.

        Returns:
            tuple: (dx, energy_new, rho) where rho is the gain ratio of the last trial.
        """
        rho = None
        dx = None
        energy_new = energy_old

        for trial in range(max_trials):
            dx = self._solve_damped_system()

            # Predicted reduction from the quadratic model (see docstring)
            predicted_reduction = self.mu * np.dot(dx, dx) - np.dot(self.b, dx)

            # Evaluate energy at trial position
            energy_new = self.evaluate_energy_fast(self.X, dx)

            # Compute actual reduction and gain ratio
            actual_reduction = energy_old - energy_new

            if predicted_reduction > 1e-15:
                rho = actual_reduction / predicted_reduction
            else:
                # Model predicts no decrease (numerically converged): accept only
                # a step that does not increase the energy.
                rho = 1.0 if actual_reduction >= 0 else -1.0

            # Decide to accept or reject step
            if rho > 0.0:
                # Adjust damping based on gain ratio
                if rho > 0.75:
                    self.mu = max(self.mu / 3.0, 1e-12)
                elif rho < 0.25:
                    self.mu = min(self.mu * 2.0, 1e12)

                # Accept step
                self._take_step(dx)
                self.energy.append(energy_new)

                if self.it == 0 or energy_new < self.energy[self.bestit]:
                    self.bestX = self.X.copy()
                    self.bestit = self.it

                if self.verbose and trial > 0:
                    print(f"      Step accepted after {trial+1} trial(s) (ρ={rho:.3f}, μ={self.mu:.3e})")

                return dx, energy_new, rho

            else:
                # Reject step and increase damping
                self.mu = min(self.mu * 4.0, 1e12)
                if self.verbose:
                    print(f"      Trial {trial+1}: rejected (ρ={rho:.3f}), increasing μ to {self.mu:.3e}")

        # Every trial increased the energy: stay at X.
        if self.verbose:
            print(f"      Max trials ({max_trials}) rejected, keeping the current point")

        self.energy.append(energy_old)
        self.prevdx = 0.0
        if self.bestit is None:
            self.bestX = self.X.copy()
            self.bestit = self.it

        return np.zeros_like(dx), energy_old, rho


    def optimize_step(self) -> None:
        """
        Executes one iteration of the Levenberg–Marquardt method.

        If adaptive_mu is True, uses adaptive damping with step acceptance/rejection.
        If adaptive_mu is False, uses simple LM that always accepts steps.
        """      
        init_time = tm.time()
        self._init_mu()
        energy_old = self._total_energy  # All terms — consistent with evaluate_energy_fast

        if self.adaptive_mu:
            dx, energy_new, rho = self._LM_adaptive(energy_old)
        else:
            dx, energy_new, rho = self._LM_simple()

        lm_time = tm.time() - init_time

        # Build header string on first iteration
        if self.it == 0:
            mode_str = "Adaptive" if self.adaptive_mu else "Simple"
            header = "=" * 90 + "\n"
            header += f"Levenberg-Marquardt Optimization ({mode_str})\n"
            header += f"{'Iter':<6} | {'Energy':<13} | {'Norm Energy':<13} | {'||dx||':<13} | {'μ':<13} | {'ρ':<8} | {'Time':<8}\n"
            header += "-" * 90
            self.log += header + "\n"
            if self.verbose:
                print(header)

        self.iter_time.append(lm_time)

        # Store iteration data in a DataFrame (optional)
        new_row = {
            'Iteration': self.it + 1,
            'Energy': self.energy[-1],
            'Norm_Energy': sum(self.norm_energy_dic.values()),
            'Step_Norm': self.prevdx,
            'Mu': self.mu,
            'Rho': rho,
            'Time': lm_time
        }
        self.dataFrameOptimization = pd.concat([self.dataFrameOptimization, pd.DataFrame([new_row])], ignore_index=True)
    

        # Build iteration summary string
        energy_norm = sum(self.norm_energy_dic.values())
        rho_str = f"{rho:.4f}" if rho is not None else "N/A"
        iter_line = f"{self.it+1:<6} | {self.energy[-1]:<13.6e} | {energy_norm:<13.6e} | {self.prevdx:<13.6e} | {self.mu:<13.6e} | {rho_str:<8} | {lm_time:<8.4f}"
        self.log += iter_line + "\n"
        if self.verbose and ((self.it + 1) % 10 == 0 or self.it == 0):
            print(iter_line)

        self.it += 1
 

    def optimize(self, max_iter: int = 100, tol: float = 1e-8) -> bool:
        """
        Runs the optimization loop until convergence or until the maximum number of iterations is reached.
        
        Args:
            max_iter (int): Maximum number of iterations.
            tol (float): Convergence tolerance for the change in energy.
        
        Returns:
            bool: True if the optimization converged; False if it reached max_iter,
            was stopped (opt.stop = True) or failed.

        Raises:
            RuntimeError: If the optimizer is not properly initialized.
        """
        if self.X is None:
            raise RuntimeError("Optimizer not initialized. Call initialize_optimizer() first.")

        if self.verbose:
            mode = "adaptive LM" if self.adaptive_mu else "fixed-damping LM"
            print(f"Starting {mode} optimization (max_iter={max_iter}, tol={tol})")

        while self.it < max_iter and not self.stop:
            try:
                # Check convergence before computing new gradients
                if self._check_convergence(tol):
                    if self.verbose:
                        print(f"Converged at iteration {self.it} with energy {self.energy[-1]:.6e}")
                    return True
                
                # Compute gradients and accumulate energies
                self.get_gradients()
                # Perform an optimization step (LM or PG)
                self.optimize_step()

            except Exception as e:
                print(f"Optimization failed at iteration {self.it}: {str(e)}")
                self.stop = True
                return False

        if self.verbose:
            if self.stop:
                print(f"Optimization stopped at iteration {self.it}")
            else:
                print(f"Reached maximum iterations ({max_iter})")
        return False

    def _check_convergence(self, tol: float) -> bool:
        """
        Checks whether the optimization has converged based on the change in energy or the step size.
        
        Args:
            tol (float): Tolerance value for convergence.
        
        Returns:
            bool: True if the change in energy or step norm is below tolerance, else False.
        """
        if len(self.energy) < 2:
            return False

        energy_change = abs(self.energy[-1] - self.energy[-2])
        if energy_change < tol or self.prevdx is not None and self.prevdx < tol:
            return True

        # if self.prevdx is not None and self.prevdx < tol:
        #     return True

        return False

    def get_variables(self) -> np.ndarray:
        """
        Prints and returns the best variable vector found.
        
        Returns:
            np.ndarray: The best variable vector.
        """
        print(f"Best iteration: {self.bestit + 1}\tBest energy: {self.energy[self.bestit]}")
        return self.bestX

    def get_data_frame_optimization(self) -> pd.DataFrame:
        """
        Returns the DataFrame containing optimization iteration data.

        Returns:
            pd.DataFrame: DataFrame with iteration details.
        """
        return self.dataFrameOptimization
    
    def print_report(self) -> None:
        """
        Print weights, iterations and energy per constraint in a formatted table.
        """
        report = self.get_report()
        print(report)

    def get_report(self) -> str:
        """
        Returns weights, iterations and energy per constraint as a formatted string.

        Returns:
            str: The formatted report.
        """
        lines = []
        sep = "=" * 80

        # Weights section
        lines.append(f"\n{sep}")
        lines.append(" WEIGHTS REPORT")
        lines.append(sep)
        if self.objective_terms:
            max_name_len = max(len(name) for name in self.objective_terms)
            lines.append(f"{'Term':<{max_name_len}}  {'Weight':>12}")
            lines.append("-" * (max_name_len + 14))
            for name, term in self.objective_terms.items():
                lines.append(f"{name:<{max_name_len}}  {term.w:>12.4e}")
        else:
            lines.append("No objective terms registered.")

        # Iterations
        lines.append(sep)
        lines.append(f" Total Iterations: {self.it}")
        lines.append(f" Time per Iteration: {np.mean(self.iter_time) if self.iter_time else 0.0:.4f} seconds")

        # Energy section
        lines.append(sep)
        lines.append(" ENERGY REPORT")
        lines.append(sep)
        if self.energy_dic:
            total_energy = sum(energy if self.objective_terms[name].consider_energy and self.objective_terms[name].w > 1e-12 else 0.0 for name, energy in self.energy_dic.items())
            max_name_len = max(len(name) for name in self.energy_dic)
            lines.append(f"{'Term':<{max_name_len}}  {'Energy':>14}  {'Normalized':>14}  {'Contrib.':>8}")
            lines.append("-" * (max_name_len + 42))
            for name, energy in self.energy_dic.items():
                if self.objective_terms[name].consider_energy and self.objective_terms[name].w > 1e-12:
                    norm_energy = self.norm_energy_dic.get(name, 0.0)
                    pct = 100.0 * energy / total_energy if total_energy > 0 else 0.0
                    lines.append(f"{name:<{max_name_len}}  {energy:>14.6e}  {norm_energy:>14.6e}  {pct:>7.1f}%")
        else:
            lines.append("No energy data recorded.")

        # Final energy summary
        lines.append(sep)
        lines.append(" FINAL ENERGY SUMMARY")
        lines.append(sep)
        if self.energy:
            lines.append(f"  Final Energy:    {self.energy[-1]:.6e}")
            if self.bestit is not None:
                lines.append(f"  Best Iteration:  {self.bestit + 1}")
                lines.append(f"  Best Energy:     {self.energy[self.bestit]:.6e}")
        else:
            lines.append("  No optimization performed yet.")
        lines.append(sep + "\n")

        return "\n".join(lines)

    def print_energy_report(self) -> None:
        """
        Prints the energy contributions per constraint.
        """
        print("ENERGY REPORT")
        print("===========================================")
        for name, energy in self.energy_dic.items():
            print(f"{name}: {energy}")
        print("===========================================")
        print("=============Final Energy ==================")
        print(f"Final Energy: {self.energy[-1]}")
        print(f"Best iteration: {self.bestit + 1}\nBest energy: {self.energy[self.bestit]}\n")

    def unpack(self, *v_idx) -> np.ndarray:
        """
        Extracts a sub-vector from the variable vector based on the provided variable name(s).
        
        Args:
            *v_idx: One or more variable names.
        
        Returns:
            np.ndarray: The extracted variable sub-vector(s).
        """
        if len(v_idx) == 1:
            return self.X[self.var_idx[v_idx[0]]]
        else:
            return [self.X[self.var_idx[k]] for k in v_idx]

    def __del__(self):
        if self._executor is not None:
            self._executor.shutdown(wait=False)

    def __getstate__(self):
        # The thread pool holds a _queue.SimpleQueue and is not picklable.
        # Drop it; _executor=None is a valid state (gradients fall back to serial)
        # and initialize_optimizer() rebuilds it on the next setup.
        state = self.__dict__.copy()
        state['_executor'] = None
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._executor = None

    # ------------------------ Built-in Soft Constraints ------------------------

    def control_variable(self, var_name: str, w: float) -> None:
        """
        Adds a step control constraint that limits the change (step size) of a variable.
        
        Args:
            var_name (str): The variable name.
            w (float): The weight for this constraint.
        """
        sc = StepControl()
        sc._initialize_objective(self.X, self.var_idx, var_name)
        sc.consider_energy = True
        sc.w = w
        sc.name = var_name + "_step_control"
        self.objective_terms[sc.name] = sc

    def proximity_reference(self, var_name: str, vertices_Reference, faces_Reference, w_proximity: float, w_gliding: float) -> None:
        """
        Adds a proximity constraint to keep vertices close to a reference mesh. 
        Args:
            var_name (str): The variable name representing vertex positions.
            vertices_Reference: Reference mesh vertices.
            faces_Reference: Reference mesh faces.
            w_proximity (float): Weight for the proximity term.
            w_gliding (float): Weight for the gliding term.
        """

        proximity_term = ProximityReference()
        proximity_term.name = var_name + "_proximity"
        proximity_term._initialize_objective(self.X, self.var_idx, var_name, vertices_Reference, faces_Reference)
        proximity_term.consider_energy = True
        proximity_term.w = w_proximity
        self.objective_terms[proximity_term.name] = proximity_term

        gliding_term = GlideReference()
        gliding_term.name = var_name + "_gliding"
        gliding_term._initialize_objective(self.X, self.var_idx, var_name, vertices_Reference, faces_Reference)
        gliding_term.consider_energy = True
        gliding_term.w = w_gliding
        self.objective_terms[gliding_term.name] = gliding_term


    def set_lap_smooth(self, var_name: str, indices: np.ndarray, adj_list: list, dim: int, damp_factor=0.9, damp_iteration=10, w=0.001, ce=False) -> None:
        """
        Adds a fairness constraint to smooth out variations among adjacent vertices.
        
        Args:
            var_name (str): The variable name for which fairness is enforced.
            adj_list: List of adjacent vertices indices.
            dec_fac (float): Decrease factor for fairness weight.
            dec_step (float): Step decrement for fairness weight.
            dim (int): Dimension of the variable.
            w (float): Weight of the constraint.
        """
        fairness = LaplacianFairness()
        fairness.consider_energy = ce
        fairness._initialize_objective(self.X, self.var_idx, var_name, indices, adj_list, dim, damp_factor, damp_iteration)
        fairness.w = w
        self.objective_terms[fairness.name] = fairness

    def set_fairness(self, var_name: str, adj_list,  dim: int, damp_factor=0.9, damp_iteration=10, w=0.001, ce=False) -> None:
        """
        Adds a fairness constraint to smooth out variations among adjacent vertices.
        Args:
            var_name (str): The variable name for which fairness is enforced.
            adj_list: List of adjacent vertices indices.
            damp_factor (float): Decrease factor for fairness weight.
            damp_iteration (float): Number of iterations after which the weight is set 0    .
            dim (int): Dimension of the variable.
            w (float): Weight of the constraint.
        """

        variable4_idx = []
        variable4_adj_list = []

        lapVar_idx = []
        lapVar_adj_list = []
        # Separate adjacent terms for Laplacian and quadratic fairness
        for i, neighbors in enumerate(adj_list):
            if len(neighbors) == 4:
                variable4_idx.append(i)
                variable4_adj_list.append(neighbors)
            else: 
                lapVar_idx.append(i)
                
                lapVar_adj_list.append(neighbors)


        if len(variable4_idx) > 0:
            print(f"Adding quadratic fairness for {len(variable4_idx)} vertices with 4 neighbors")
            quadFariness = QuadFairness()
            quadFariness.name = "quad_fairness_"+var_name
            quadFariness.consider_energy = ce
            quadFariness._initialize_objective(self.X, self.var_idx, var_name, variable4_idx, variable4_adj_list, dim, damp_factor, damp_iteration)
            quadFariness.w = w
            self.objective_terms[quadFariness.name] = quadFariness

        if len(lapVar_idx) > 0:
            print(f"Adding Laplacian fairness for {len(lapVar_idx)} ")
            lapFairness = LaplacianFairness()
            lapFairness.name = "lap_fairness_"+var_name
            lapFairness.consider_energy = ce
            lapFairness._initialize_objective(self.X, self.var_idx, var_name, lapVar_idx, lapVar_adj_list, dim, damp_factor, damp_iteration)
            lapFairness.w = w
            self.objective_terms[lapFairness.name] = lapFairness

    def unitize_variable(self, var_name: str, dim: int, w: float) -> None:
        """
        Adds a unit vector constraint to enforce that a variable has unit norm.
        
        Args:
            var_name (str): The variable name.
            dim (int): The dimension of the variable.
            w (float): Weight of the unit objective term.
        """
        unit_term = Unit()
        unit_term._initialize_objective(self.X, self.var_idx, var_name, dim)
        unit_term.consider_energy = False
        unit_term.w = w
        unit_term.name = var_name + "_unit"
        self.objective_terms[unit_term.name] = unit_term

    def edge_length(self, var_name: str, edges, target_length:None, w: float) -> None:
        """
        Adds an edge length constraint to enforce specific lengths for edges.
        
        Args:
            var_name (str): The variable name representing vertex positions.
            edges: List of edge vertex index pairs.
            target_lengths: Target lengths for each edge.
            w (float): Weight of the edge length constraint.
        """
        edge_length_term = EdgeLength()
        edge_length_term._initialize_objective(self.X, self.var_idx, var_name, edges, target_length)
        edge_length_term.consider_energy = True
        edge_length_term.w = w
        self.objective_terms[edge_length_term.name] = edge_length_term
