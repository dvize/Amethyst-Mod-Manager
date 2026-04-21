"""
Mouse wheel event compatibility between Tk 8.6 and Tk 9.0 on Linux.

Tk 8.6 (AppImage): X11 wheel notches arrive as <Button-4>/<Button-5> only.
Tk 9.0 (Flatpak):  TIP 474 translates Button-4/5 into <MouseWheel> with
                   event.delta of +/-120 per notch, but bindings on the
                   literal <Button-4>/<Button-5> still fire. Without a guard
                   every notch scrolls twice.

Usage: wrap <Button-4>/<Button-5> handlers with ``skip_if_mousewheel`` (or
check ``LEGACY_WHEEL_REDUNDANT`` directly) so they no-op on Tk >= 8.7.
"""

from __future__ import annotations

import sys
import tkinter as tk
from typing import Callable

LEGACY_WHEEL_REDUNDANT: bool = float(tk.TkVersion) >= 8.7


def skip_if_mousewheel(fn: Callable) -> Callable:
    """Make a <Button-4>/<Button-5> handler no-op when Tk also fires <MouseWheel>.

    On Tk >= 8.7 the equivalent <MouseWheel> event already runs this widget's
    wheel logic for the same notch, so firing the Button-4/5 handler too would
    double-scroll. Return ``None`` (not ``"break"``) so other unrelated
    Button-4/5 bindings on the widget still run normally.
    """
    if not LEGACY_WHEEL_REDUNDANT:
        return fn

    def _wrapped(*_args, **_kwargs):
        return None

    return _wrapped


def patch_ctk_scrollable_frame() -> None:
    """Patch CTkScrollableFrame's Linux wheel handler to scale event.delta.

    The bundled customtkinter calls ``yview_scroll(-event.delta, "units")`` on
    Linux, which was fine on Tk 8.6 (delta was +/-1). On Tk 9.0 TIP 474 makes
    delta +/-120 per notch, so a single wheel tick scrolls 120 units and
    instantly flings the content to the end. Reduce it to +/-3 units per notch
    to match the rest of the app.
    """
    try:
        import customtkinter as ctk
        ScrollableFrame = ctk.CTkScrollableFrame
    except Exception:
        return

    def _patched_mouse_wheel_all(self, event):
        if not self.check_if_master_is_canvas(event.widget):
            return
        delta = getattr(event, "delta", 0) or 0
        if delta == 0:
            return
        if sys.platform.startswith("win"):
            units = -int(delta / 6)
        elif sys.platform == "darwin":
            units = -delta
        else:
            units = -3 if delta > 0 else 3
        if self._shift_pressed:
            if self._parent_canvas.xview() != (0.0, 1.0):
                self._parent_canvas.xview("scroll", units, "units")
        else:
            if self._parent_canvas.yview() != (0.0, 1.0):
                self._parent_canvas.yview("scroll", units, "units")

    ScrollableFrame._mouse_wheel_all = _patched_mouse_wheel_all
