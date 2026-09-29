"""
Polyhedral mesh optimization — a hanan + kayviz example.

    python examples/polyhedral_mesh/run.py [path/to/quad_mesh.obj]

Opens the viewer in the browser. "Initialize Optimizer" builds the planarity and
cyclicity energies (hanan.optimization); "Run All" streams Gauss-Newton steps to
the viewer until "Stop" or Max Iterations.
"""

import os
import sys

import kayviz as kv
from app import PolyhedralMeshApp

HERE = os.path.dirname(os.path.abspath(__file__))

mesh_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "data", "pq_mesh.obj")

kv.register_app(PolyhedralMeshApp(mesh_path), panel_js="polyhedral_panel.js")
kv.show()
