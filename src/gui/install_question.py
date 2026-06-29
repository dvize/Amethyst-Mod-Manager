"""
install_question.py
Generic single-choice question overlay for install-time wizards.

Shows an in-app overlay (CTkFrame placed over the mod-panel container) matching
the BainDialog / FOMOD installer pattern, rather than a popup Toplevel.

``ask_choice(title, prompt, options, default_index) -> str | None``
"""

from __future__ import annotations

import threading
import traceback as _traceback
import tkinter as tk

import customtkinter as ctk

from gui.wheel_compat import LEGACY_WHEEL_REDUNDANT
from gui.theme import (
    BG_DEEP, BG_PANEL, BG_HEADER, BG_CARD, BORDER,
    ACCENT, ACCENT_HOV, TEXT_ON_ACCENT, TEXT_MAIN, TEXT_DIM,
    BTN_WARN_ORANGE, BTN_WARN_ORANGE_HOV,
)


# Navigation sentinels are owned by Utils.ui_hooks so the backend and GUI
# compare against the *same* objects (identity comparison). Re-exported here for
# existing call sites.
#   BACK         — user pressed "Back" to revisit the previous wizard page.
#   USE_DEFAULTS — user accepts the default for this and all remaining pages.
from Utils.ui_hooks import BACK, USE_DEFAULTS


class _ChoiceOverlay(ctk.CTkFrame):
    """Full-panel overlay asking the user to pick one of several options."""

    def __init__(self, parent, title: str, prompt: str,
                 options: list[str], default_index: int = 0, on_done=None,
                 page: int = 0, total_pages: int = 0):
        super().__init__(parent, fg_color=BG_DEEP, corner_radius=0)
        self._on_done = on_done or (lambda r: None)
        self.result: str | None = None

        # Header
        bar = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=0, height=40)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        ctk.CTkLabel(bar, text=title, text_color=TEXT_MAIN,
                     font=ctk.CTkFont(weight="bold")).pack(
            side="left", padx=16, pady=8)
        if total_pages > 1:
            ctk.CTkLabel(bar, text=f"Page {page} of {total_pages}",
                         text_color=TEXT_DIM).pack(side="right", padx=16, pady=8)

        # Footer first (packed to bottom) so it always stays on screen even
        # when the scrollable body grows past the panel height.
        footer = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=0, height=50)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        ctk.CTkFrame(footer, fg_color=BORDER, height=1,
                     corner_radius=0).pack(fill="x", side="top")
        # Footer buttons pack right-to-left. Match the FOMOD layout: Cancel is
        # rightmost, Back sits directly to its left, then OK.
        ctk.CTkButton(footer, text="Cancel", width=90,
                      fg_color=BG_CARD, hover_color=BG_HEADER,
                      text_color=TEXT_DIM,
                      command=self._on_cancel).pack(
            side="right", padx=(4, 14), pady=8)
        # Back — only meaningful past the first page of a multi-page wizard.
        if page > 1:
            ctk.CTkButton(footer, text="Back", width=90,
                          fg_color=BG_CARD, hover_color=BG_HEADER,
                          text_color=TEXT_DIM,
                          command=self._on_back).pack(
                side="right", padx=4, pady=8)
        ctk.CTkButton(footer, text="OK", width=90,
                      fg_color=ACCENT, hover_color=ACCENT_HOV,
                      text_color=TEXT_ON_ACCENT,
                      command=self._on_ok).pack(
            side="right", padx=4, pady=8)
        # Install-with-defaults shortcut — accepts the default selection for
        # every remaining page. Orange to set it apart as a bulk action.
        if total_pages > 1:
            ctk.CTkButton(footer, text="Use Defaults", width=120,
                          fg_color=BTN_WARN_ORANGE,
                          hover_color=BTN_WARN_ORANGE_HOV,
                          text_color=TEXT_ON_ACCENT,
                          command=self._on_use_defaults).pack(
                side="left", padx=14, pady=8)

        # Body — scrollable so many options stay reachable on small screens.
        body = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                      corner_radius=0)
        body.pack(fill="both", expand=True, padx=20, pady=16)
        self._body = body
        self._setup_scroll_binding(body)

        ctk.CTkLabel(body, text=prompt, justify="left",
                     text_color=TEXT_DIM, wraplength=500).pack(
            anchor="w", pady=(0, 12))

        safe_idx = max(0, min(default_index, len(options) - 1)) if options else 0
        self._var = tk.StringVar(value=options[safe_idx] if options else "")

        card = ctk.CTkFrame(body, fg_color=BG_PANEL, corner_radius=6)
        card.pack(fill="x", anchor="w")
        for opt in options:
            rb = ctk.CTkRadioButton(card, text=opt,
                                    variable=self._var, value=opt,
                                    text_color=TEXT_MAIN)
            rb.pack(anchor="w", padx=14, pady=5)

    def _setup_scroll_binding(self, scroll) -> None:
        """Bind the scrollwheel globally so the options scroll regardless of
        pointer position. Matches the BainDialog / FOMOD wizard sensitivity."""
        canvas = getattr(scroll, "_parent_canvas", None)
        if canvas is None:
            return
        self._bound_root = None

        def _on_scroll(event):
            try:
                if not scroll.winfo_exists():
                    return
                sx = scroll.winfo_rootx()
                sy = scroll.winfo_rooty()
                sw = scroll.winfo_width()
                sh = scroll.winfo_height()
            except Exception:
                return
            if sx <= event.x_root < sx + sw and sy <= event.y_root < sy + sh:
                num = getattr(event, "num", None)
                delta = getattr(event, "delta", 0) or 0
                if num == 4 or delta > 0:
                    direction = -3
                elif num == 5 or delta < 0:
                    direction = 3
                else:
                    return
                canvas.yview("scroll", direction, "units")

        # On Tk >= 8.7 CTkScrollableFrame already handles <MouseWheel> via its
        # own bind_all — we only need to supplement Button-4/5 for Tk 8.6.
        if not LEGACY_WHEEL_REDUNDANT:
            root = self.winfo_toplevel()
            root.bind_all("<Button-4>", _on_scroll, add="+")
            root.bind_all("<Button-5>", _on_scroll, add="+")
            self._bound_root = root
            self._scroll_handler = _on_scroll

    def _teardown_scroll_binding(self) -> None:
        root = getattr(self, "_bound_root", None)
        if root is None:
            return
        try:
            root.unbind_all("<Button-4>")
            root.unbind_all("<Button-5>")
        except Exception:
            pass
        self._bound_root = None

    def _on_ok(self) -> None:
        self._finish(self._var.get() or None)

    def _on_cancel(self) -> None:
        self._finish(None)

    def _on_back(self) -> None:
        self._finish(BACK)

    def _on_use_defaults(self) -> None:
        self._finish(USE_DEFAULTS)

    def _finish(self, result) -> None:
        cb = self._on_done
        self._teardown_scroll_binding()
        try:
            self.destroy()
        finally:
            cb(result)


def _resolve_root() -> "tk.Misc | None":
    root = getattr(tk, "_default_root", None)
    try:
        if root is not None and root.winfo_exists():
            return root
    except Exception:
        pass
    return None


def _show_on_main(root, title, prompt, options, default_index, on_done,
                  log_fn=None, page=0, total_pages=0) -> None:
    """Create + place the overlay. Must run on the main thread."""
    _log = log_fn or (lambda _: None)
    try:
        container = getattr(root, "_mod_panel_container", None) or root
        panel = _ChoiceOverlay(container, title, prompt, options,
                               default_index, on_done=on_done,
                               page=page, total_pages=total_pages)
        if panel.winfo_exists():
            panel.place(relx=0, rely=0, relwidth=1, relheight=1)
            panel.lift()
            panel.focus_set()
    except Exception as exc:
        _log(f"  [DAO] overlay creation failed: {exc!r}")
        for line in _traceback.format_exc().rstrip().splitlines():
            _log(f"    {line}")
        on_done(None)


def ask_choice(title: str, prompt: str, options: list[str],
               default_index: int = 0, log_fn=None,
               page: int = 0, total_pages: int = 0) -> str | None:
    """Show a single-choice overlay. Returns the chosen label or None."""
    _log = log_fn or (lambda _: None)
    if not options:
        return None
    root = _resolve_root()
    if root is None:
        _log("  [DAO] no Tk root available — keeping defaults.")
        return None

    if threading.current_thread() is threading.main_thread():
        done_var = tk.BooleanVar(value=False)
        holder: list = [None]

        def _on_done_main(result):
            holder[0] = result
            done_var.set(True)

        try:
            _show_on_main(root, title, prompt, options, default_index,
                          _on_done_main, log_fn=_log,
                          page=page, total_pages=total_pages)
            root.wait_variable(done_var)
        except Exception as exc:
            _log(f"  [DAO] overlay failed (main thread): {exc!r}")
            return None
        return holder[0]

    # Worker thread path
    holder2: list = [None]
    done = threading.Event()

    def _on_done_worker(result):
        holder2[0] = result
        done.set()

    root.after(0, lambda: _show_on_main(
        root, title, prompt, options, default_index,
        _on_done_worker, log_fn=_log, page=page, total_pages=total_pages))
    done.wait()
    return holder2[0]
