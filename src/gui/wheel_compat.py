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
