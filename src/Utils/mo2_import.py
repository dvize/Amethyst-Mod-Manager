"""
mo2_import.py — Import mods, overwrite, and profiles from a Mod Organizer 2 instance.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from Utils.app_log import app_log


def validate_mo2_folder(mo2_path: Path) -> str | None:
    """Return an error string if *mo2_path* doesn't look like a valid MO2 folder,
    or ``None`` if it's fine."""
    if not mo2_path.is_dir():
        return f"Folder does not exist:\n{mo2_path}"
    if not (mo2_path / "mods").is_dir():
        return f"No 'mods' folder found in:\n{mo2_path}"
    return None


def count_mo2_mods(mo2_path: Path) -> int:
    """Return the number of mod folders inside the MO2 mods/ directory."""
    mods_dir = mo2_path / "mods"
    if not mods_dir.is_dir():
        return 0
    return sum(1 for p in mods_dir.iterdir() if p.is_dir())


def import_mo2(mo2_path: Path, staging_root: Path,
               log_fn=None) -> None:
    """Move MO2 mods/, overwrite/, and profiles/ into *staging_root*.

    *staging_root* is the value of ``game.get_profile_root()`` — the directory
    that already contains the manager's own ``mods/``, ``profiles/``, etc.

    Existing items in the destination are **not** overwritten; conflicting mod
    folders are skipped with a warning.
    """
    log = log_fn or app_log

    for sub in ("mods", "overwrite", "profiles"):
        src = mo2_path / sub
        if not src.is_dir():
            log(f"MO2 {sub}/ not found — skipping.")
            continue

        dst = staging_root / sub
        dst.mkdir(parents=True, exist_ok=True)

        if sub == "mods":
            _move_mods(src, dst, log)
        elif sub == "profiles":
            _move_contents(src, dst, sub, log, suffix=" Mo2")
        else:
            _move_contents(src, dst, sub, log)

    log("MO2 import complete.")


def _move_mods(src: Path, dst: Path, log) -> None:
    """Move each mod folder individually so we can skip conflicts."""
    moved = 0
    skipped = 0
    for mod_dir in sorted(src.iterdir()):
        if not mod_dir.is_dir():
            continue
        target = dst / mod_dir.name
        if target.exists():
            log(f"  Skipped (already exists): {mod_dir.name}")
            skipped += 1
            continue
        shutil.move(str(mod_dir), str(target))
        moved += 1
    log(f"Mods moved: {moved}" + (f", skipped: {skipped}" if skipped else ""))


def _move_contents(src: Path, dst: Path, label: str, log,
                    suffix: str = "") -> None:
    """Move contents of *src* into *dst* (for overwrite / profiles).

    If *suffix* is set, it is appended to each item's name on the
    destination side (e.g. ``" Mo2"`` for imported profiles).
    """
    moved = 0
    for item in sorted(src.iterdir()):
        dest_name = item.name + suffix if suffix else item.name
        target = dst / dest_name
        if target.exists():
            log(f"  Skipped {label}/{item.name} (already exists)")
            continue
        shutil.move(str(item), str(target))
        moved += 1
    log(f"{label.capitalize()} items moved: {moved}")
