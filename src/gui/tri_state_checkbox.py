"""Tri-state checkbox wrapper for filter panels.

States: 0 = off, 1 = include (accent check), 2 = exclude (red minus).
Clicking cycles 0 -> 1 -> 2 -> 0. Backed by a tk.IntVar so existing
BooleanVar-shaped code can be migrated with minimal change (treat
0 == False, 1/2 == truthy, then read .get() for the actual state).
"""

import tkinter as tk
import customtkinter as ctk


STATE_OFF = 0
STATE_INCLUDE = 1
STATE_EXCLUDE = 2

EXCLUDE_COLOR = "#c0392b"
EXCLUDE_HOVER = "#9c2c20"


class TriStateCheckBox(ctk.CTkCheckBox):
    """CTkCheckBox that cycles through three states on click.

    The Tk variable (must be IntVar) holds 0/1/2. `command` is called
    after every state change.
    """

    def __init__(self, master, *, variable: tk.IntVar | None = None,
                 fg_color=None, hover_color=None, **kwargs):
        # CTkCheckBox stores its accent (include) color in fg_color.
        # We keep our own copy of both the include and exclude palettes
        # so _draw() can swap between them based on the tri-state.
        self._include_fg = fg_color
        self._include_hover = hover_color
        self._exclude_fg = EXCLUDE_COLOR
        self._exclude_hover = EXCLUDE_HOVER

        if variable is None:
            variable = tk.IntVar(value=0)
        self._tri_var = variable

        # Bridge: CTkCheckBox uses a BooleanVar-style on/off model; we
        # keep its internal variable bound to a private BooleanVar that
        # mirrors "is the box visually checked at all" (state != 0).
        self._bridge_var = tk.BooleanVar(value=variable.get() != STATE_OFF)

        super().__init__(
            master,
            variable=self._bridge_var,
            fg_color=fg_color,
            hover_color=hover_color,
            **kwargs,
        )

        # The first draw happens before our overrides take effect, so
        # force a redraw once construction is finished.
        self._apply_state_colors()
        self._draw()

    # ------------------------------------------------------------------
    # State accessors
    # ------------------------------------------------------------------

    def get_state(self) -> int:
        return self._tri_var.get()

    def set_state(self, state: int) -> None:
        state = int(state) % 3
        self._tri_var.set(state)
        self._bridge_var.set(state != STATE_OFF)
        self._check_state = state != STATE_OFF
        self._apply_state_colors()
        self._draw()

    # ------------------------------------------------------------------
    # Click handling — cycle 0 -> 1 -> 2 -> 0
    # ------------------------------------------------------------------

    def toggle(self, event=0):
        if self._state != tk.NORMAL:
            return
        cur = self._tri_var.get()
        nxt = (cur + 1) % 3
        self._tri_var.set(nxt)
        self._bridge_var.set(nxt != STATE_OFF)
        self._check_state = nxt != STATE_OFF
        self._apply_state_colors()
        self._draw()
        if self._command is not None:
            self._command()

    # ------------------------------------------------------------------
    # Visual swap
    # ------------------------------------------------------------------

    def _apply_state_colors(self) -> None:
        """Swap fg/hover colors to match include vs exclude palette."""
        state = self._tri_var.get()
        if state == STATE_EXCLUDE:
            self._fg_color = self._exclude_fg
            self._hover_color = self._exclude_hover
        else:
            self._fg_color = self._include_fg
            self._hover_color = self._include_hover

    def _draw(self, no_color_updates=False):
        # Let the parent draw box + check normally. We then either show
        # the check (include state) or hide it and overlay our own minus
        # glyph (exclude state). We keep the minus under a different tag
        # ("tristate_minus") so the parent's coords("checkmark", ...) call
        # never tries to reposition our 4-coord line.
        super()._draw(no_color_updates)
        state = self._tri_var.get()
        self._canvas.delete("tristate_minus")
        if state == STATE_EXCLUDE:
            # Hide the parent's checkmark item without destroying it.
            try:
                self._canvas.itemconfigure("checkmark", state="hidden")
            except Exception:
                pass
            w = self._apply_widget_scaling(self._checkbox_width)
            h = self._apply_widget_scaling(self._checkbox_height)
            pad = w * 0.22
            y = h / 2
            self._canvas.create_line(
                pad, y, w - pad, y,
                width=max(2, int(self._apply_widget_scaling(2.5))),
                fill=self._apply_appearance_mode(self._checkmark_color),
                capstyle="round",
                tags="tristate_minus",
            )
            self._canvas.tag_raise("tristate_minus")
        else:
            # Make sure the parent's checkmark is visible again when we
            # come back to include / off states.
            try:
                self._canvas.itemconfigure("checkmark", state="normal")
            except Exception:
                pass
