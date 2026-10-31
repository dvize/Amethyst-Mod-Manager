"""
warhammer_40k_rogue_trader.py
Game handler for Warhammer 40,000: Rogue Trader.

Mod structure:
  Rogue Trader reads mods from two folders inside the Proton prefix:

  * Unity Mod Manager (UMM) mods - a folder containing ``Info.json``:
      drive_c/users/steamuser/AppData/LocalLow/Owlcat Games/
        Warhammer 40000 Rogue Trader/UnityModManager/<ModName>/
    UMM is built into the game, so nothing has to be installed for these.

  * Owlcat Template mods - a folder containing
    ``OwlcatModificationManifest.json``:
      .../Warhammer 40000 Rogue Trader/Modifications/<UniqueName>/
    Owlcat only loads modifications named in the sibling
    ``OwlcatModificationManagerSettings.json``; post_deploy() registers the
    deployed names there and restore() removes them again.

  * Portrait packs for the CustomNpcPortraits UMM mod - either a folder of
    PNGs below ``NPCs/`` and/or ``Companions/`` (optionally wrapped in
    ``Portraits/`` or ``CustomNpcPortraits/Portraits/``), or a bare ``<Name>/``
    character folder holding ``Small/Medium/Fulllength.png``.  These are not
    UMM mods themselves, so they are merged into the framework's data folder:
      .../UnityModManager/CustomNpcPortraits/Portraits/<NPCs|Companions>/<Name>/...

  Staged mods live in Profiles/Warhammer 40,000: Rogue Trader/mods/.  Every
  mod must sit in a named subfolder (``mod_staging_requires_subdir``); flat
  archives are auto-wrapped before the filemap is built.

Notes:
  * Per-mod custom deploy directories (separators) are not supported.
  * Steam App ID 2186680; Nexus domain ``warhammer40kroguetrader``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from Games.base_game import BaseGame
from Utils.atomic_write import write_atomic_text
from Utils.config_paths import get_profiles_dir
from Utils.deployment import (
    LinkMode, deploy_filemap, deploy_core, cleanup_custom_deploy_dirs,
    move_to_core, restore_data_core,
)
from Utils.mods.modlist import read_modlist

_PROFILES_DIR = get_profiles_dir()

# Owlcat's per-user data root inside the Proton prefix.  Note the game folder
# has no comma in it even though the store title does.
_RT_DATA_SUBPATH = Path(
    "drive_c/users/steamuser/AppData/LocalLow/Owlcat Games/"
    "Warhammer 40000 Rogue Trader"
)
_UMM_SUBPATH = _RT_DATA_SUBPATH / "UnityModManager"
_MODIFICATIONS_SUBPATH = _RT_DATA_SUBPATH / "Modifications"

_OWLCAT_SETTINGS_NAME = "OwlcatModificationManagerSettings.json"
_MANAGED_MODS_NAME = "owlcat_deployed_mods.json"

_UMM_MARKER = "info.json"
_OWLCAT_MARKER = "owlcatmodificationmanifest.json"

# Portrait packs for the CustomNpcPortraits UMM mod are plain PNG trees that
# must be merged under the framework's own folder, not dropped beside it.
_PORTRAIT_DEST_PREFIX = "CustomNpcPortraits/Portraits/"
_PORTRAIT_DIRS = {"npcs", "companions"}
# The three PNGs every CustomNpcPortraits character folder carries.
_PORTRAIT_SIZES = {"small.png", "medium.png", "fulllength.png"}
# Companion display names the framework resolves by name (its ReadMe list).  A
# bare ``<Name>/`` portrait folder is a companion unless the name is not here,
# in which case it is treated as a generic NPC.
_PORTRAIT_COMPANIONS = {
    "abelard", "idira", "argenta", "cassia", "pasqal", "heinrix",
    "jae", "yrliet", "ulfar", "marazhai", "kibellah",
}


class Warhammer40kRogueTrader(BaseGame):

    def __init__(self):
        self._game_path: Path | None = None
        self._prefix_path: Path | None = None
        self._deploy_mode: LinkMode = LinkMode.HARDLINK
        self._staging_path: Path | None = None
        self.load_paths()

    # -----------------------------------------------------------------------
    # Identity
    # -----------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "Warhammer 40,000: Rogue Trader"

    @property
    def game_id(self) -> str:
        return "warhammer_40k_rogue_trader"

    @property
    def exe_name(self) -> str:
        return "WH40KRT.exe"

    @property
    def steam_id(self) -> str:
        return "2186680"

    @property
    def nexus_game_domain(self) -> str:
        return "warhammer40kroguetrader"

    @property
    def plugin_extensions(self) -> list[str]:
        return []

    @property
    def default_deploy_mode(self) -> str:
        # Staging usually lives on a different filesystem from the prefix, and
        # UMM loads symlinked assemblies without complaint.
        return "symlink"

    extra_open_locations = (
        ("UnityModManager mods",
         "{prefix}/" + str(_UMM_SUBPATH)),
        ("Owlcat modifications",
         "{prefix}/" + str(_MODIFICATIONS_SUBPATH)),
    )

    # -- Mod structure -------------------------------------------------------

    @property
    def mod_staging_requires_subdir(self) -> bool:
        # Both UMM and Owlcat mods are a named folder with a manifest inside.
        return True

    @property
    def mod_staging_wrap_signals(self) -> "tuple[set[str], set[str]]":
        return ({_UMM_MARKER, _OWLCAT_MARKER}, set())

    @property
    def mod_staging_already_structured_markers(self) -> "set[str]":
        return {_UMM_MARKER, _OWLCAT_MARKER}

    # -----------------------------------------------------------------------
    # Paths
    # -----------------------------------------------------------------------

    def get_game_path(self) -> Path | None:
        return self._game_path

    def get_mod_data_path(self) -> Path | None:
        """Mods deploy into the prefix's UnityModManager folder."""
        if self._prefix_path is None:
            return None
        return self._prefix_path / _UMM_SUBPATH

    def get_mod_staging_path(self) -> Path:
        if self._staging_path is not None:
            return self._staging_path / "mods"
        return _PROFILES_DIR / self.name / "mods"

    def get_hardlink_deploy_targets(self) -> list[tuple[str, "Path | None"]]:
        return [("Proton prefix", self._prefix_path)]

    def set_staging_path(self, path: "Path | str | None") -> None:
        self._staging_path = Path(path) if path else None
        self.save_paths()

    def get_deploy_mode(self) -> LinkMode:
        return self._deploy_mode

    def set_deploy_mode(self, mode: LinkMode) -> None:
        self._deploy_mode = mode
        self.save_paths()

    # -----------------------------------------------------------------------
    # Mod classification
    # -----------------------------------------------------------------------

    @staticmethod
    def _find_marker(root: Path, marker: str, depth: int = 2) -> Path | None:
        """Return the shallowest file named *marker* under *root* (casefold)."""
        try:
            children = sorted(root.iterdir(), key=lambda c: c.name.lower())
        except OSError:
            return None
        for child in children:
            if child.is_file() and child.name.lower() == marker:
                return child
        if depth <= 0:
            return None
        for child in children:
            if child.is_dir():
                found = Warhammer40kRogueTrader._find_marker(
                    child, marker, depth - 1)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _read_unique_name(manifest: Path, fallback: str) -> str:
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            unique = data.get("UniqueName") or data.get("uniqueName")
        except Exception:
            unique = None
        if not isinstance(unique, str) or not unique.strip():
            return fallback
        unique = unique.strip()
        if any(sep in unique for sep in ("/", "\\", "\x00")) or unique in (".", ".."):
            return fallback
        return unique

    @staticmethod
    def _portrait_rel(mod_dir: Path, root: Path) -> str:
        """Staging-relative folder prefix for *root* (``""`` for the mod dir).

        The filemap strips the staging folder name, so remap prefixes are
        relative to *mod_dir*, not to the staging root.
        """
        rel = root.relative_to(mod_dir).as_posix()
        return "" if rel == "." else rel + "/"

    @classmethod
    def _find_portrait_pack(cls, mod_dir: Path, max_depth: int = 3):
        """Locate a CustomNpcPortraits pack inside *mod_dir*.

        Returns ``(src_prefix, dest_prefix)`` - the staging-relative folder
        that holds the portrait tree and the UnityModManager-relative folder
        it must be merged into - or ``None`` when *mod_dir* is not a portrait
        pack.

        Two layouts are recognised:

        * an explicit ``NPCs/`` and/or ``Companions/`` tree of PNGs (with or
          without a ``Portraits/`` wrapper): merged under
          ``CustomNpcPortraits/Portraits/`` unchanged;
        * a bare ``<Name>/`` folder holding the three portrait PNGs, which the
          framework expects under ``Companions/`` for a known companion and
          ``NPCs/`` otherwise.

        The PNG guards keep an unrelated UMM mod that merely has an ``NPCs``
        data folder from being rerouted, and the digit guard keeps the game's
        own numeric portrait slots (character-creator packs) out of the
        framework, which only resolves folders by character name.
        """
        queue: list[tuple[Path, int]] = [(mod_dir, 0)]
        while queue:
            current, depth = queue.pop(0)
            try:
                subdirs = {c.name.lower(): c for c in current.iterdir()
                           if c.is_dir()}
            except OSError:
                continue
            groups = _PORTRAIT_DIRS & subdirs.keys()
            if groups and any(cls._contains_png(subdirs[n]) for n in groups):
                prefix = cls._portrait_rel(mod_dir, current)
                if prefix:
                    return prefix, _PORTRAIT_DEST_PREFIX
            if cls._is_portrait_folder(current) and not current.name.isdigit():
                prefix = cls._portrait_rel(mod_dir, current)
                if prefix:
                    group = ("Companions" if current.name.casefold()
                             in _PORTRAIT_COMPANIONS else "NPCs")
                    dest = f"{_PORTRAIT_DEST_PREFIX}{group}/{current.name}/"
                    return prefix, dest
            if depth < max_depth:
                queue.extend((d, depth + 1) for d in subdirs.values())
        return None

    @staticmethod
    def _is_portrait_folder(folder: Path) -> bool:
        """True when *folder* holds the three CustomNpcPortraits PNGs."""
        try:
            names = {c.name.casefold() for c in folder.iterdir() if c.is_file()}
        except OSError:
            return False
        return _PORTRAIT_SIZES <= names

    @staticmethod
    def _contains_png(root: Path, max_depth: int = 4) -> bool:
        stack: list[tuple[Path, int]] = [(root, 0)]
        while stack:
            current, depth = stack.pop()
            try:
                for child in current.iterdir():
                    if child.is_file() and child.suffix.lower() == ".png":
                        return True
                    if child.is_dir() and depth < max_depth:
                        stack.append((child, depth + 1))
            except OSError:
                continue
        return False

    def _classify_staged_mods(self):
        """Split staged mod folders into UMM, portrait and Owlcat targets.

        Returns ``(umm_mods, owl_mods, portrait_mods)`` where *umm_mods* is a
        set of staging folder names, *owl_mods* maps a staging folder name to
        ``(UniqueName, filemap_prefix)`` and *portrait_mods* maps a staging
        folder name to ``(src_prefix, dest_prefix)`` - the filemap-relative
        folder to remap and the ``UnityModManager/``-relative folder it becomes.
        """
        umm_mods: set[str] = set()
        owl_mods: dict[str, tuple[str, str]] = {}
        portrait_mods: dict[str, tuple[str, str]] = {}
        staging = self.get_effective_mod_staging_path()
        if not staging.is_dir():
            return umm_mods, owl_mods, portrait_mods
        for mod_dir in sorted(staging.iterdir(), key=lambda p: p.name.lower()):
            if not mod_dir.is_dir():
                continue
            if self._find_marker(mod_dir, _UMM_MARKER) is not None:
                umm_mods.add(mod_dir.name)
                continue
            owl_marker = self._find_marker(mod_dir, _OWLCAT_MARKER)
            if owl_marker is not None:
                unique = self._read_unique_name(owl_marker, mod_dir.name)
                try:
                    prefix = owl_marker.parent.relative_to(staging).as_posix()
                except ValueError:
                    prefix = mod_dir.name
                owl_mods[mod_dir.name] = (unique, prefix + "/")
                continue
            portrait_pack = self._find_portrait_pack(mod_dir)
            if portrait_pack is not None:
                portrait_mods[mod_dir.name] = portrait_pack
                umm_mods.add(mod_dir.name)
                continue
            # Unknown layout - treat as a UMM mod, the common case.
            umm_mods.add(mod_dir.name)
        return umm_mods, owl_mods, portrait_mods


    # -----------------------------------------------------------------------
    # Deployment
    # -----------------------------------------------------------------------

    def deploy(self, log_fn=None, mode: LinkMode = LinkMode.HARDLINK,
               profile: str = "default", progress_fn=None) -> None:
        """Deploy staged mods into the prefix's UMM and Modifications folders.

        Workflow (per target folder):
          1. Move the current contents to <Folder>_Core/  (vanilla backup)
          2. Transfer the mods' filemap entries into <Folder>/
          3. Fill gaps with the backed-up vanilla files
        UMM mods keep their staging folder under UnityModManager/, portrait
        packs are merged into UnityModManager/CustomNpcPortraits/Portraits/,
        and Owlcat mods go to Modifications/ (each remapped from its staging
        folder to its UniqueName).
        """
        _log = log_fn or (lambda _: None)

        if self._prefix_path is None:
            raise RuntimeError("Prefix path is not configured.")

        from Utils.filegraph.deploy import input_ready, entries
        if not input_ready():
            raise RuntimeError(
                f"filemap not found: {self.get_effective_filemap_path()}\n"
                "Run 'Build Filemap' before deploying."
            )

        umm_mods, owl_mods, portrait_mods = self._classify_staged_mods()
        all_rel = {e.legacy_rel.lower() for e in entries() if e.legacy_rel}
        owl_rel = {e.legacy_rel.lower() for e in entries()
                   if e.legacy_rel and e.mod_name in owl_mods}
        owl_exclude = all_rel - owl_rel

        umm_dir = self._prefix_path / _UMM_SUBPATH
        mods_dir = self._prefix_path / _MODIFICATIONS_SUBPATH
        staging = self.get_effective_mod_staging_path()
        filemap = self.get_effective_filemap_path()

        # -- UMM pass --------------------------------------------------------
        umm_dir.mkdir(parents=True, exist_ok=True)
        _log("Step 1: Backing up UnityModManager/ ...")
        move_to_core(umm_dir, log_fn=_log)
        _log(f"Step 2: Deploying {len(umm_mods)} UMM mod(s) "
             f"into UnityModManager/ ({mode.name}) ...")
        umm_remap = {src: dest for src, dest in portrait_mods.values()}
        if portrait_mods:
            _log(f"  Merging {len(portrait_mods)} portrait pack(s) into "
                 f"UnityModManager/{_PORTRAIT_DEST_PREFIX} ...")
        linked_umm, placed_umm = deploy_filemap(
            filemap, umm_dir, staging, exclude=owl_rel, mode=mode,
            path_remap=umm_remap or None, log_fn=_log, progress_fn=progress_fn)

        linked_umm_core = deploy_core(umm_dir, placed_umm, mode=mode, log_fn=_log)
        _log(f"  Transferred {linked_umm} mod + {linked_umm_core} vanilla "
             f"file(s).")

        # -- Owlcat pass -----------------------------------------------------
        mods_dir.mkdir(parents=True, exist_ok=True)
        _log("Step 3: Backing up Modifications/ ...")
        move_to_core(mods_dir, log_fn=_log)
        remap = {prefix: f"{unique}/"
                 for unique, prefix in owl_mods.values()}
        _log(f"Step 4: Deploying {len(owl_mods)} Owlcat mod(s) "
             f"into Modifications/ ({mode.name}) ...")
        linked_owl, placed_owl = deploy_filemap(
            filemap, mods_dir, staging, exclude=owl_exclude, mode=mode,
            path_remap=remap or None, log_fn=_log, progress_fn=progress_fn)
        linked_owl_core = deploy_core(mods_dir, placed_owl, mode=mode, log_fn=_log)
        _log(f"  Transferred {linked_owl} mod + {linked_owl_core} vanilla "
             f"file(s).")

        # Owlcat's loader enumerates <mod>/Assemblies unconditionally in
        # Apply_Patch0; the filemap only carries files, so a blueprint-only mod
        # (no DLLs) would otherwise fail with DirectoryNotFoundException and
        # never apply. Recreate the empty placeholder after every deploy, using
        # the deployed folder names - they are not always the manifest's
        # UniqueName, and a placeholder in the wrong folder makes Owlcat abort
        # descriptor loading (then the in-game manager shows zero mods).
        created = 0
        removed = 0
        for mod_dir in sorted(mods_dir.iterdir()):
            if not mod_dir.is_dir():
                continue
            children = list(mod_dir.iterdir())
            if any(child.name.lower() == _OWLCAT_MARKER for child in children):
                assemblies = mod_dir / "Assemblies"
                if assemblies.is_dir():
                    continue
                try:
                    assemblies.mkdir(parents=True, exist_ok=True)
                    created += 1
                except OSError as exc:
                    _log(f"  WARN: could not create {assemblies}: {exc}")
                continue
            # Manifest-less leftover (empty, or an Assemblies-only folder from
            # an older deploy): Owlcat fails the whole descriptor scan on it.
            if all(child.name == "Assemblies" for child in children):
                try:
                    shutil.rmtree(mod_dir)
                    removed += 1
                except OSError as exc:
                    _log(f"  WARN: could not remove {mod_dir}: {exc}")
        if created:
            _log(f"  Created {created} empty Assemblies/ placeholder(s).")
        if removed:
            _log(f"  Removed {removed} stray mod folder(s) without a manifest.")

        self._record_managed_mods(filemap.parent, owl_mods, log_fn=_log)
        # Record the game root so restore() can tell runtime-generated files
        # (Player.log, crash dumps) from files we deployed.
        self.snapshot_root_for_runtime_capture(log_fn=_log)
        _log("Deploy complete.")

    def _record_managed_mods(self, profile_dir: Path, owl_mods, log_fn=None) -> None:
        """Persist staging-folder -> UniqueName so restore() can unregister."""
        _log = log_fn or (lambda _: None)
        managed = profile_dir / _MANAGED_MODS_NAME
        if owl_mods:
            payload = {stage: unique for stage, (unique, _p) in owl_mods.items()}
            try:
                write_atomic_text(managed, json.dumps(payload, indent=2) + "\n")
            except OSError as exc:
                _log(f"  WARN: could not record Owlcat mod list: {exc}")
        else:
            try:
                managed.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                _log(f"  WARN: could not clear Owlcat mod list: {exc}")

    def post_deploy(self, log_fn=None) -> None:
        """Register deployed Owlcat mods with the in-game mod manager."""
        _log = log_fn or (lambda _: None)
        managed = self.get_effective_filemap_path().parent / _MANAGED_MODS_NAME
        names = set(self._read_managed_mods(managed).values())
        if not names:
            return
        try:
            self._edit_owlcat_settings(add=names, log_fn=_log)
            _log(f"  Registered {len(names)} Owlcat mod(s) with "
                 f"{_OWLCAT_SETTINGS_NAME}.")
        except Exception as exc:
            _log(f"  WARN: could not update {_OWLCAT_SETTINGS_NAME}: {exc}")

    @staticmethod
    def _read_managed_mods(path: Path) -> dict[str, str]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()
                if isinstance(v, str) and v}

    def _edit_owlcat_settings(self, add=(), remove=(), log_fn=None) -> None:
        """Merge *add* / drop *remove* in the Owlcat mod-manager settings."""
        _log = log_fn or (lambda _: None)
        path = self._prefix_path / _RT_DATA_SUBPATH / _OWLCAT_SETTINGS_NAME
        data: dict = {}
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("not a JSON object")
                data = raw
            except Exception as exc:
                backup = path.with_name(path.name + ".bak")
                try:
                    path.replace(backup)
                except OSError:
                    backup = None
                _log(f"  WARN: {_OWLCAT_SETTINGS_NAME} unreadable ({exc}) - "
                     + (f"backed up to {backup.name}." if backup else
                        "rewriting it."))
                data = {}
        remove = set(remove)
        for key in ("EnabledModifications", "ActiveModifications"):
            current = data.get(key)
            values = [v for v in current
                      if isinstance(v, str)] if isinstance(current, list) else []
            merged = [v for v in values if v not in remove]
            for name in add:
                if name not in merged:
                    merged.append(name)
            data[key] = merged
        data.setdefault("$id", "1")
        data.setdefault("SourceDirectories", [])
        data.setdefault("DisabledModifications", [])
        write_atomic_text(path, json.dumps(data, indent=2) + "\n")

    def restore(self, log_fn=None, progress_fn=None) -> None:
        """Remove deployed mods and restore the vanilla mod folders."""
        _log = log_fn or (lambda _: None)

        if self._prefix_path is None:
            raise RuntimeError("Prefix path is not configured.")

        _profile_dir = self._active_profile_dir
        _entries = read_modlist(_profile_dir / "modlist.txt") if _profile_dir else []
        cleanup_custom_deploy_dirs(_profile_dir, _entries, log_fn=_log, game=self)
        self.capture_runtime_files_to_root_folder(log_fn=_log)

        umm_dir = self._prefix_path / _UMM_SUBPATH
        mods_dir = self._prefix_path / _MODIFICATIONS_SUBPATH

        managed = self.get_effective_filemap_path().parent / _MANAGED_MODS_NAME
        names = set(self._read_managed_mods(managed).values())

        _log("Restore: clearing UnityModManager/ and moving its backup back ...")
        restored_umm = restore_data_core(
            umm_dir, overwrite_dir=self.get_effective_overwrite_path(),
            log_fn=_log, game=self, profile_dir=self._active_profile_dir)
        _log(f"  Restored {restored_umm} file(s).")

        _log("Restore: clearing Modifications/ and moving its backup back ...")
        restored_owl = restore_data_core(
            mods_dir, overwrite_dir=self.get_effective_overwrite_path(),
            log_fn=_log, game=self, profile_dir=self._active_profile_dir)
        _log(f"  Restored {restored_owl} file(s).")

        settings = self._prefix_path / _RT_DATA_SUBPATH / _OWLCAT_SETTINGS_NAME
        if names and settings.is_file():
            try:
                self._edit_owlcat_settings(remove=names, log_fn=_log)
            except Exception as exc:
                _log(f"  WARN: could not update {_OWLCAT_SETTINGS_NAME}: {exc}")

        try:
            managed.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            _log(f"  WARN: could not clear Owlcat mod list: {exc}")

        _log("Restore complete.")
