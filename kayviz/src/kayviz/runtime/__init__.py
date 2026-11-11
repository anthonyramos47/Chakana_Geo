"""
webscope — Polyscope-style framework for Three.js GUI apps.

Public API:
    Scene           — geometry builder context manager
    GUIApp          — base class for app implementations
    ScriptApp       — always-registered broadcast app for the scripting API
    CallbackApp     — auto-panel app driven by a Python callback function
    register_app    — register an app with the framework
    mount_all       — mount all registered apps onto a FastAPI instance
    gui_state       — class decorator for state dataclasses
    slider          — widget helper: float slider
    int_slider      — widget helper: integer slider
    dropdown        — widget helper: dropdown/select
    checkbox        — widget helper: boolean checkbox
    text_field      — widget helper: text input
    to_json         — extract widget schema from a @gui_state class
    apply_client_state — apply a client payload dict to a state instance
    script          — Polyscope-style scripting module (import as ws)
    imgui           — Polyscope-style widget helpers for use inside callbacks
"""

from .scene import Scene
from .app import GUIApp
from .script_app import ScriptApp
from .callback_app import CallbackApp
from .registry import register_app, mount_all
from .state_schema import (
    gui_state,
    slider,
    int_slider,
    dropdown,
    checkbox,
    text_field,
    to_json,
    apply_client_state,
)
from . import script
from . import imgui

__all__ = [
    "Scene",
    "GUIApp",
    "ScriptApp",
    "CallbackApp",
    "register_app",
    "mount_all",
    "gui_state",
    "slider",
    "int_slider",
    "dropdown",
    "checkbox",
    "text_field",
    "to_json",
    "apply_client_state",
    "script",
    "imgui",
]
