"""
wine_dll_config.py
Shared helpers for per-game Wine DLL override storage and deployment.

Storage format (~/.config/AmethystModManager/games/<game>/wine_dll_overrides.json):
{
  "overrides": {"winhttp": "native,builtin", ...}
}
"""

from __future__ import annotations

import json
from pathlib import Path

from Utils.config_paths import get_game_config_dir


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _overrides_path(game_name: str) -> Path:
    return get_game_config_dir(game_name) / "wine_dll_overrides.json"


def _load_raw(game_name: str) -> dict:
    p = _overrides_path(game_name)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def load_wine_dll_overrides(game_name: str) -> dict[str, str]:
    """Load stored Wine DLL overrides, returning {} on error."""
    data = _load_raw(game_name)
    # Support old flat format ({dll: mode}) and new nested format
    raw = data.get("overrides", data) if "overrides" in data else data
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if k and not k.startswith("_")}
    return {}


def save_wine_dll_overrides(game_name: str, overrides: dict[str, str]) -> None:
    """Persist Wine DLL overrides to config."""
    p = _overrides_path(game_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"overrides": overrides}, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Deploy helper
# ---------------------------------------------------------------------------

def deploy_game_wine_dll_overrides(
    game_name: str,
    prefix_path: Path,
    handler_overrides: dict[str, str],
    log_fn=None,
) -> None:
    """Merge handler overrides with stored config and apply to the prefix."""
    _log = log_fn or (lambda _: None)

    stored = load_wine_dll_overrides(game_name)
    # Handler overrides are always present; user overrides sit on top
    to_apply: dict[str, str] = {**handler_overrides, **stored}
    # Handler DLLs not in stored yet should be persisted
    if handler_overrides:
        for dll, mode in handler_overrides.items():
            stored.setdefault(dll, mode)
        save_wine_dll_overrides(game_name, stored)

    if not to_apply:
        return

    _log("Applying Wine DLL overrides to Proton prefix ...")
    from Utils.deploy import apply_wine_dll_overrides
    apply_wine_dll_overrides(prefix_path, to_apply, log_fn=_log)



# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _overrides_path(game_name: str) -> Path:
    return get_game_config_dir(game_name) / "wine_dll_overrides.json"


def _load_raw(game_name: str) -> dict:
    p = _overrides_path(game_name)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def load_wine_dll_overrides(game_name: str) -> dict[str, str]:
    """Load stored Wine DLL overrides, returning {} on error."""
    data = _load_raw(game_name)
    # Support old flat format ({dll: mode}) and new nested format
    raw = data.get("overrides", data) if "overrides" in data else data
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if k and not k.startswith("_")}
    return {}


def load_wine_dll_excluded(game_name: str) -> set[str]:
    """Return the set of DLL names the user has explicitly removed."""
    data = _load_raw(game_name)
    excluded = data.get("excluded", [])
    if isinstance(excluded, list):
        return {str(e).lower() for e in excluded if e}
    return set()


def save_wine_dll_overrides(
    game_name: str,
    overrides: dict[str, str],
    excluded: "set[str] | None" = None,
) -> None:
    """Persist Wine DLL overrides (and optional excluded set) to config."""
    p = _overrides_path(game_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"overrides": overrides}
    if excluded:
        data["excluded"] = sorted(excluded)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def merge_handler_overrides(
    game_name: str,
    handler_overrides: dict[str, str],
) -> dict[str, str]:
    """Return stored overrides merged with handler overrides.

    Handler-defined overrides are skipped when they appear in the stored
    excluded set (i.e. the user previously removed them via the panel).
    """
    stored = load_wine_dll_overrides(game_name)
    excluded = load_wine_dll_excluded(game_name)
    merged = dict(stored)
    for dll, mode in handler_overrides.items():
        if dll and dll not in merged and dll.lower() not in excluded:
            merged[dll] = mode
    return merged


# ---------------------------------------------------------------------------
# Deploy helper
# ---------------------------------------------------------------------------

def deploy_game_wine_dll_overrides(
    game_name: str,
    prefix_path: Path,
    handler_overrides: dict[str, str],
    log_fn=None,
) -> None:
    """Merge handler overrides with stored config and apply to the prefix.

    This is the single entry-point every game handler's deploy() should call
    instead of calling apply_wine_dll_overrides() directly.  It:
      1. Builds the set to apply: user-stored (non-excluded) + ALL handler
         overrides.  Handler overrides bypass excluded because they are
         required by the game — excluded only controls panel visibility.
      2. Persists the non-excluded portion back to storage so the panel
         reflects the current state without resurfacing handler DLLs the
         user removed.
      3. Applies the full merged set to the Proton prefix.
    """
    _log = log_fn or (lambda _: None)

    stored   = load_wine_dll_overrides(game_name)
    excluded = load_wine_dll_excluded(game_name)

    # Handler DLLs are always active — remove them from excluded so they
    # appear in the panel and aren't suppressed on future deploys
    handler_lower = {d.lower() for d in handler_overrides}
    excluded -= handler_lower

    # User-added overrides that haven't been explicitly excluded
    to_apply: dict[str, str] = {
        k: v for k, v in stored.items()
        if k.lower() not in excluded
    }
    # Handler overrides always applied and always visible in the panel
    to_apply.update(handler_overrides)

    save_wine_dll_overrides(game_name, to_apply, excluded)

    if not to_apply:
        return

    from Utils.deploy import apply_wine_dll_overrides
    apply_wine_dll_overrides(prefix_path, to_apply, log_fn=_log)
