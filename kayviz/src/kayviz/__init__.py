"""
kayviz — Polyscope-style 3D viewer in the browser.

A script is its own app:

    import kayviz as kv

    kv.init()                                       # viewer server for this process
    kv.register_surface_mesh("Mesh", V, F)
    kv.add_scalar_quantity("Mesh", "curvature", K)

    state = {"steps": 10}
    def gui():
        kv.imgui.slider_int("Steps", state, "steps", 1, 100)
        if kv.imgui.button("Smooth"):
            kv.register_surface_mesh("Mesh", smooth(V, F, state["steps"]), F)
    kv.set_user_callback(gui)

    kv.show()                                       # open the browser tab

Larger apps subclass ``kv.GUIApp`` (a ``@gui_state`` dataclass plus action
handlers, optionally a custom panel module) and are served with
``kv.register_app(MyApp())`` followed by ``kv.show()``.

Building blocks:
    kv.serializers  — geometry → JSON dicts understood by the viewer
    kv.Scene        — collect serializer dicts inside a computation
    kv.server       — create_app() for running kayviz under your own uvicorn
"""

__version__ = "0.2.0"

from .webscope.script import (
    init,
    url,
    show,
    register_surface_mesh,
    register_curve_network,
    register_point_cloud,
    register_vector_field,
    add_scalar_quantity,
    add_vector_quantity,
    set_enabled,
    remove,
    clear,
    push_objects,
    set_user_callback,
    register_app,
    screenshot,
    screenshot_views,
    save_grid,
    get_camera,
    DEFAULT_VIEWS,
    FITTED_VIEWS,
    TIGHT_VIEWS,
)
from .webscope import (
    Scene,
    GUIApp,
    ScriptApp,
    CallbackApp,
    mount_all,
    gui_state,
    slider,
    int_slider,
    dropdown,
    checkbox,
    text_field,
    to_json,
    apply_client_state,
)
from .webscope import script
from .webscope import imgui
from . import serializers

__all__ = [
    # scripting
    "init", "url", "show",
    "register_surface_mesh", "register_curve_network", "register_point_cloud",
    "register_vector_field", "add_scalar_quantity", "add_vector_quantity",
    "set_enabled", "remove", "clear", "push_objects",
    "set_user_callback", "register_app",
    "screenshot", "screenshot_views", "save_grid", "get_camera",
    "DEFAULT_VIEWS", "FITTED_VIEWS", "TIGHT_VIEWS",
    # app framework
    "Scene", "GUIApp", "ScriptApp", "CallbackApp", "mount_all",
    "gui_state", "slider", "int_slider", "dropdown", "checkbox", "text_field",
    "to_json", "apply_client_state",
    # modules
    "script", "imgui", "serializers",
]
