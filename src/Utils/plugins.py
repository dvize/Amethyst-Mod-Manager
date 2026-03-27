"""
plugins.py
Read and write a MO2-compatible plugins.txt file.

Format (one plugin per line):
  *PluginName.esp   — enabled plugin
  PluginName.esp    — disabled plugin (no prefix)

Order in the file defines load order (line 0 = first loaded).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

@dataclass
class PluginEntry:
    name: str
    enabled: bool


def _normalise_ext(name: str) -> str:
    """Return name with its file extension lowercased (e.g. Mod.ESP → Mod.esp)."""
    dot = name.rfind(".")
    if dot == -1:
        return name
    return name[:dot] + name[dot:].lower()


def read_plugins(path: Path, star_prefix: bool = True) -> list[PluginEntry]:
    """
    Parse plugins.txt and return entries in file order (index 0 = first loaded).
    Lines that are blank or start with '#' are skipped.

    When star_prefix is True (default, MO2-style):
      '*Name' = enabled; bare 'Name' = disabled.
    When star_prefix is False (e.g. Oblivion Remastered):
      All listed plugins are enabled; no '*' prefix is used.
    """
    entries: list[PluginEntry] = []
    if not path.is_file():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if star_prefix:
            if line.startswith("*"):
                name = line[1:]
                entries.append(PluginEntry(name=_normalise_ext(name), enabled=True))
            else:
                entries.append(PluginEntry(name=_normalise_ext(line), enabled=False))
        else:
            entries.append(PluginEntry(name=_normalise_ext(line), enabled=True))
    return entries


def write_plugins(path: Path, entries: list[PluginEntry], star_prefix: bool = True) -> None:
    """
    Write entries back to plugins.txt.
    Creates parent directories if needed.

    When star_prefix is True (default, MO2-style):
      Enabled entries are written as '*Name', disabled as bare 'Name'.
    When star_prefix is False (e.g. Oblivion Remastered):
      All entries are written as bare 'Name' (the game has no '*' syntax).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        (f"*{e.name}" if e.enabled else e.name) if star_prefix else e.name
        for e in entries
    ]
    path.write_text(
        "\n".join(lines) + ("\n" if lines else ""),
        encoding="utf-8",
    )


def read_loadorder(path: Path) -> list[str]:
    """Read loadorder.txt and return plugin names in order.

    loadorder.txt stores the full load order including vanilla plugins
    (which are excluded from plugins.txt).  One bare filename per line.
    """
    if not path.is_file():
        return []
    names: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.append(line)
    return names


def write_loadorder(path: Path, entries: list[PluginEntry]) -> None:
    """Write the full load order (bare filenames) to loadorder.txt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [e.name for e in entries]
    path.write_text(
        "\n".join(lines) + ("\n" if lines else ""),
        encoding="utf-8",
    )


def append_plugin(path: Path, plugin_name: str, enabled: bool = True,
                  star_prefix: bool = True) -> None:
    """
    Append a plugin to the bottom of plugins.txt if not already present.
    The check is case-insensitive so 'Plugin.esp' and 'plugin.esp' are treated
    as the same plugin.
    Does nothing if the plugin already exists in the file.
    """
    entries = read_plugins(path, star_prefix=star_prefix)
    existing_lower = {e.name.lower() for e in entries}
    if plugin_name.lower() in existing_lower:
        return
    entries.append(PluginEntry(name=plugin_name, enabled=enabled))
    write_plugins(path, entries, star_prefix=star_prefix)


def prune_plugins_from_filemap(
    filemap_path: Path,
    plugins_path: Path,
    plugin_extensions: list[str],
    data_dir: Path | None = None,
    star_prefix: bool = True,
) -> int:
    """
    Remove entries from plugins.txt whose plugin file no longer appears in
    filemap.txt (i.e. the mod providing that plugin was disabled).

    Plugins that exist in data_dir (vanilla game plugins) are always kept,
    even if absent from the filemap.

    Only root-level files are considered (matching how Bethesda plugins work).
    Returns the count of removed entries.
    """
    if not plugin_extensions:
        return 0

    exts_lower = {ext.lower() for ext in plugin_extensions}

    # Collect all root-level plugin filenames present in the current filemap
    in_filemap: set[str] = set()
    if filemap_path.is_file():
        with filemap_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if "\t" not in line:
                    continue
                rel_path, _ = line.split("\t", 1)
                rel_path = rel_path.replace("\\", "/")
                if "/" in rel_path:
                    continue
                if Path(rel_path).suffix.lower() in exts_lower:
                    in_filemap.add(rel_path.lower())

    # Also keep plugins that exist as vanilla files in the game's Data/ dir.
    # Prefer Data_Core/ when it exists — after deployment Data/ contains
    # hard-linked mod files, so Data_Core/ is the reliable source of truth
    # for what plugins are truly vanilla.
    in_data_dir: set[str] = set()
    if data_dir and data_dir.is_dir():
        vanilla_dir = data_dir.parent / (data_dir.name + "_Core")
        scan_dir = vanilla_dir if vanilla_dir.is_dir() else data_dir
        for entry in scan_dir.iterdir():
            if entry.is_file() and entry.suffix.lower() in exts_lower:
                in_data_dir.add(entry.name.lower())

    keep = in_filemap | in_data_dir
    existing = read_plugins(plugins_path, star_prefix=star_prefix)
    kept = [e for e in existing if e.name.lower() in keep]
    removed = len(existing) - len(kept)
    if removed:
        write_plugins(plugins_path, kept, star_prefix=star_prefix)
    return removed


def sync_plugins_from_data_dir(
    data_dir: Path,
    plugins_path: Path,
    plugin_extensions: list[str],
    star_prefix: bool = True,
) -> int:
    """
    Scan the game's Data directory for root-level plugin files and append any
    not already in plugins.txt (e.g. vanilla ESMs like Fallout4.esm).
    Returns the count of newly added plugins.
    """
    if not plugin_extensions or not data_dir.is_dir():
        return 0

    exts_lower = {ext.lower() for ext in plugin_extensions}
    existing = read_plugins(plugins_path, star_prefix=star_prefix)
    existing_lower = {e.name.lower() for e in existing}

    new_entries: list[PluginEntry] = []
    for entry in data_dir.iterdir():
        if entry.is_file() and entry.suffix.lower() in exts_lower:
            if entry.name.lower() not in existing_lower:
                new_entries.append(PluginEntry(name=entry.name, enabled=True))
                existing_lower.add(entry.name.lower())

    if new_entries:
        write_plugins(plugins_path, existing + new_entries, star_prefix=star_prefix)

    return len(new_entries)


def sync_plugins_from_overwrite_dir(
    overwrite_dir: Path,
    plugins_path: Path,
    plugin_extensions: list[str],
    star_prefix: bool = True,
) -> int:
    """
    Scan the overwrite folder for root-level plugin files and append any
    not already in plugins.txt. Also updates loadorder.txt so new plugins
    appear in the plugins panel.

    Scans both overwrite root and overwrite/Data/ (Bethesda games mirror
    the Data folder structure when rescuing runtime-created files).

    The filemap is built from modindex.bin, which only updates overwrite on
    Refresh. Tools like xEdit or Bodyslide may write plugins directly to
    overwrite without triggering a refresh. This direct scan ensures those
    plugins still get added to plugins.txt and loadorder.txt.

    Returns the count of newly added plugins.
    """
    if not plugin_extensions or not overwrite_dir.is_dir():
        return 0

    exts_lower = {ext.lower() for ext in plugin_extensions}
    existing = read_plugins(plugins_path, star_prefix=star_prefix)
    existing_lower = {e.name.lower() for e in existing}

    def scan_directory(directory: Path) -> list[PluginEntry]:
        entries: list[PluginEntry] = []
        if not directory.is_dir():
            return entries
        for entry in directory.iterdir():
            if entry.is_file() and entry.suffix.lower() in exts_lower:
                if entry.name.lower() not in existing_lower:
                    entries.append(PluginEntry(name=entry.name, enabled=True))
                    existing_lower.add(entry.name.lower())
        return entries

    new_entries: list[PluginEntry] = []
    new_entries.extend(scan_directory(overwrite_dir))
    new_entries.extend(scan_directory(overwrite_dir / "Data"))

    if new_entries:
        write_plugins(plugins_path, existing + new_entries, star_prefix=star_prefix)
        # Update loadorder.txt so the plugins panel shows them
        loadorder_path = plugins_path.parent / "loadorder.txt"
        saved_order = read_loadorder(loadorder_path)
        lo_lower = {n.lower() for n in saved_order}
        appended = [e.name for e in new_entries if e.name.lower() not in lo_lower]
        if appended:
            write_loadorder(
                loadorder_path,
                [PluginEntry(name=n, enabled=True) for n in saved_order + appended],
            )

    return len(new_entries)


def sync_plugins_from_filemap(
    filemap_path: Path,
    plugins_path: Path,
    plugin_extensions: list[str],
    disabled_plugins: dict[str, list[str]] | None = None,
    star_prefix: bool = True,
) -> int:
    """
    Scan filemap.txt for files matching plugin_extensions and append any
    not already in plugins.txt.  Returns the count of newly added plugins.

    The filemap format is: <relative/path/to/file>\\t<mod_name>
    Only root-level files (no directory separator in relative path) are
    considered, because Bethesda plugins live at the root of the Data folder.

    disabled_plugins maps mod_name -> list of plugin filenames to suppress.
    """
    if not filemap_path.is_file() or not plugin_extensions:
        return 0

    exts_lower = {ext.lower() for ext in plugin_extensions}

    existing = read_plugins(plugins_path, star_prefix=star_prefix)
    existing_lower = {e.name.lower() for e in existing}

    new_entries: list[PluginEntry] = []

    with filemap_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if "\t" not in line:
                continue
            rel_path, mod_name = line.split("\t", 1)
            rel_path = rel_path.replace("\\", "/")
            if "/" in rel_path:
                # Plugin is inside a subfolder — not a root-level plugin file
                continue
            filename = rel_path
            if (Path(filename).suffix.lower() in exts_lower
                    and filename.lower() not in existing_lower):
                if disabled_plugins:
                    mod_disabled = {n.lower() for n in disabled_plugins.get(mod_name, [])}
                    if filename.lower() in mod_disabled:
                        continue
                # Normalise extension to lowercase so case-sensitive filesystems
                # (Linux) can locate the file on disk (e.g. .ESP → .esp).
                stem = Path(filename).stem
                ext  = Path(filename).suffix.lower()
                normalised = stem + ext
                new_entries.append(PluginEntry(name=normalised, enabled=True))
                existing_lower.add(normalised.lower())

    if new_entries:
        write_plugins(plugins_path, existing + new_entries, star_prefix=star_prefix)

    return len(new_entries)


def read_disabled_plugins(path: Path) -> dict[str, list[str]]:
    """Read disabled_plugins.json. Returns {} if absent or corrupt."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if isinstance(v, list)}
    except Exception:
        pass
    return {}


def write_disabled_plugins(path: Path, data: dict[str, list[str]]) -> None:
    """Write disabled_plugins.json atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read_excluded_mod_files(path: Path) -> dict[str, list[str]]:
    """Read excluded mod files. If *path* is …/excluded_mod_files.json, delegates to profile_state.

    Format: {mod_name: [rel_key_lower, ...]}
    """
    if path.name == "excluded_mod_files.json":
        from Utils.profile_state import read_excluded_mod_files as _read_ps

        return _read_ps(path.parent, None)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if isinstance(v, list)}
    except Exception:
        pass
    return {}


def write_excluded_mod_files(path: Path, data: dict[str, list[str]]) -> None:
    """Write excluded mod files. If *path* is …/excluded_mod_files.json, delegates to profile_state."""
    if path.name == "excluded_mod_files.json":
        from Utils.profile_state import write_excluded_mod_files as _write_ps

        _write_ps(path.parent, data)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
