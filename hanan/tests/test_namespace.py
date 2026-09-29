"""The package namespaces expose every public function of the geometry submodules."""

import importlib
import inspect

import pytest

import hanan.geometry
import hanan.geometry.utils

SUBMODULES = ["algebraic", "primitives", "construction", "measures", "conical", "lie",
              "isotropic_geometry", "io"]


def _public_functions(name):
    mod = importlib.import_module(f"hanan.geometry.{name}")
    return [n for n, obj in vars(mod).items()
            if not n.startswith("_") and inspect.isfunction(obj) and obj.__module__ == mod.__name__]


def test_mesh_is_exported():
    from hanan.geometry import Mesh
    assert Mesh.__name__ == "Mesh"


@pytest.mark.parametrize("name", SUBMODULES)
def test_submodule_functions_reachable(name):
    missing_pkg = [f for f in _public_functions(name) if not hasattr(hanan.geometry, f)]
    missing_utils = [f for f in _public_functions(name) if not hasattr(hanan.geometry.utils, f)]
    assert not missing_pkg, f"not exported by hanan.geometry: {missing_pkg}"
    assert not missing_utils, f"not re-exported by hanan.geometry.utils: {missing_utils}"
