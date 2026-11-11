"""
studio_demo.py — test scene for the kayviz studio render mode (bulb button).

    conda activate Lproj
    python examples/studio_demo.py

Opens the viewer with a few opaque shapes resting on a plate (ambient occlusion
shows in the creases and contacts, the soft shadow on the floor), one translucent
shell (no AO by design) and a tube curve. Toggle the bulb button (bottom left)
to compare studio on/off, and the sun/moon button for light/dark. Sliders:
Lighting -> Studio (AO strength, AO radius, shadow).
"""
import numpy as np
import kayviz as kv


def param_grid(f, nu, nv, u_range, v_range, closed_u=True, closed_v=True):
    """Quad grid of a parametrisation f(u, v) -> (..., 3); returns V, F."""
    u = np.linspace(*u_range, nu, endpoint=not closed_u)
    v = np.linspace(*v_range, nv, endpoint=not closed_v)
    U, W = np.meshgrid(u, v, indexing="ij")
    V = f(U, W).reshape(-1, 3)
    F = []
    for i in range(nu if closed_u else nu - 1):
        for j in range(nv if closed_v else nv - 1):
            a, b = i * nv + j, ((i + 1) % nu) * nv + j
            c, d = ((i + 1) % nu) * nv + (j + 1) % nv, i * nv + (j + 1) % nv
            F.append([a, b, c, d])
    return V, np.array(F)


def sphere(c, r, n=48):
    f = lambda u, v: np.stack([np.cos(u) * np.sin(v), np.cos(v), np.sin(u) * np.sin(v)], -1)
    V, F = param_grid(f, n, n // 2 + 1, (0, 2 * np.pi), (1e-3, np.pi - 1e-3), closed_v=False)
    return c + r * V, F


def torus(c, R, r, n=96, m=32):
    f = lambda u, v: np.stack([(R + r * np.cos(v)) * np.cos(u), r * np.sin(v),
                               (R + r * np.cos(v)) * np.sin(u)], -1)
    V, F = param_grid(f, n, m, (0, 2 * np.pi), (0, 2 * np.pi))
    return c + V, F


def box(c, size):
    s = np.array(size) / 2
    V = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]) * s + c
    F = [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]]
    return V, np.array(F)


def zup(P):
    """The scene below is written y-up; kayviz shows z up: (x, y, z) -> (x, -z, y)."""
    P = np.asarray(P, float)
    return np.stack([P[:, 0], -P[:, 2], P[:, 1]], axis=1)


def _z(VF):
    V, F = VF
    return zup(V), F


def push_all():
    kv.clear()
    smooth = dict(shading="smooth")          # sampled smooth surfaces, not polyhedra
    V, F = box([0, -0.05, 0], [3.0, 0.1, 2.0])
    kv.register_surface_mesh("Plate", zup(V), F, color=(0.9, 0.9, 0.9))
    kv.register_surface_mesh("Torus", *_z(torus(np.array([-0.6, 0.18, 0.0]), 0.45, 0.18)), **smooth,
                             color=(0.88, 0.40, 0.23))
    kv.register_surface_mesh("Sphere big", *_z(sphere(np.array([0.55, 0.35, -0.2]), 0.35)), **smooth,
                             color=(0.92, 0.92, 0.92))
    kv.register_surface_mesh("Sphere small", *_z(sphere(np.array([0.85, 0.15, 0.35]), 0.15)), **smooth,
                             color=(0.15, 0.15, 0.17))
    kv.register_surface_mesh("Sphere on torus", *_z(sphere(np.array([-0.6, 0.48, 0.0]), 0.2)), **smooth,
                             color=(0.30, 0.50, 0.85), show_edges=True)
    kv.register_surface_mesh("Glass shell", *_z(sphere(np.array([0.0, 0.5, 0.75]), 0.4)), **smooth,
                             color=(0.55, 0.25, 0.75), material="glass")
    t = np.linspace(0, 2 * np.pi, 200, endpoint=False)
    curve = np.stack([1.2 * np.cos(t), 0.9 + 0.15 * np.sin(3 * t), 0.8 * np.sin(t)], 1)
    kv.register_curve_network("Curve", zup(curve), [[i, (i + 1) % 200] for i in range(200)],
                              color=(0.11, 0.5, 0.23), radius=0.012)


def gui():
    pass


def main():
    kv.init()
    kv.set_user_callback(gui, app_name="studio_demo", on_load=push_all)
    kv.show(app="studio_demo", block=True)


if __name__ == "__main__":
    main()
