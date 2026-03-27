"""
plugin_parser.py
Read master-file dependencies from Bethesda plugin headers (.esp/.esm/.esl).

Only the first record (TES4/TES3) is parsed — this contains MAST subrecords
that list the plugin's required master files.

TES4 record layout (Oblivion and newer):
    type     4 bytes   "TES4"
    datasize 4 bytes   uint32 LE  (size of subrecord block, excludes header)
    flags    4 bytes
    formID   4 bytes
    vc-info  8 bytes
    -------- 24 bytes total header, then `datasize` bytes of subrecords

TES4 subrecord layout:
    type    4 bytes   e.g. "MAST", "DATA", "HEDR"
    size    2 bytes   uint16 LE
    data    `size` bytes

TES3 record layout (Morrowind):
    type     4 bytes   "TES3"
    datasize 4 bytes   uint32 LE  (size of subrecord block, excludes header)
    unknown  4 bytes
    flags    4 bytes
    -------- 16 bytes total header, then `datasize` bytes of subrecords

TES3 subrecord layout:
    type    4 bytes   e.g. "MAST", "DATA", "HEDR"
    size    4 bytes   uint32 LE   (NOT 2 bytes like TES4)
    data    `size` bytes
"""

from __future__ import annotations

import struct
from pathlib import Path


def read_masters(plugin_path: Path) -> list[str]:
    """
    Return the list of master filenames declared in a plugin's TES4 header.

    Returns an empty list on any error (missing file, corrupt header, etc.).
    """
    try:
        with plugin_path.open("rb") as f:
            # --- Record header ---
            # Read the first 8 bytes to determine type and subrecord block size,
            # then skip the rest of the record header before reading the block.
            # TES4 (Oblivion+): 24-byte header; TES3 (Morrowind): 16-byte header.
            rec_header = f.read(8)
            if len(rec_header) < 8:
                return []

            rec_type = rec_header[0:4]
            if rec_type == b"TES3":
                is_tes3 = True
                hdr_remaining = 8   # 16 total - 8 already read
            elif rec_type == b"TES4":
                is_tes3 = False
                hdr_remaining = 16  # 24 total - 8 already read
            else:
                return []

            data_size = struct.unpack_from("<I", rec_header, 4)[0]

            # Skip the rest of the record header to land at the subrecord block.
            f.read(hdr_remaining)

            # --- Subrecord block ---
            block = f.read(data_size)
            if len(block) < data_size:
                return []

            # TES3 subrecord header is 8 bytes (4-byte size field).
            # TES4 subrecord header is 6 bytes (2-byte size field).
            sub_hdr_size = 8 if is_tes3 else 6

            masters: list[str] = []
            offset = 0
            while offset + sub_hdr_size <= data_size:
                sub_type = block[offset:offset + 4]
                if is_tes3:
                    sub_size = struct.unpack_from("<I", block, offset + 4)[0]
                else:
                    sub_size = struct.unpack_from("<H", block, offset + 4)[0]
                offset += sub_hdr_size

                if offset + sub_size > data_size:
                    break

                if sub_type == b"MAST":
                    # Null-terminated string
                    raw = block[offset:offset + sub_size]
                    name = raw.rstrip(b"\x00").decode("utf-8", errors="replace")
                    if name:
                        masters.append(name)

                offset += sub_size

            return masters
    except (OSError, struct.error):
        return []


def read_masters_with_sizes(plugin_path: Path) -> dict[str, int]:
    """Return {master_filename: expected_size} from the plugin header.

    The DATA subrecord immediately following each MAST subrecord contains
    the file size (uint64 LE) of that master as recorded when the plugin
    was built. Only present in TES3 (Morrowind) format.

    Returns an empty dict on any error or for TES4+ plugins (which don't
    record master sizes in the same way).
    """
    try:
        with plugin_path.open("rb") as f:
            rec_header = f.read(8)
            if len(rec_header) < 8:
                return {}

            rec_type = rec_header[0:4]
            if rec_type == b"TES3":
                hdr_remaining = 8
            else:
                return {}  # Only meaningful for TES3

            data_size = struct.unpack_from("<I", rec_header, 4)[0]
            f.read(hdr_remaining)
            block = f.read(data_size)
            if len(block) < data_size:
                return {}

            result: dict[str, int] = {}
            last_mast: str | None = None
            offset = 0
            while offset + 8 <= data_size:
                sub_type = block[offset:offset + 4]
                sub_size = struct.unpack_from("<I", block, offset + 4)[0]
                offset += 8

                if offset + sub_size > data_size:
                    break

                if sub_type == b"MAST":
                    raw = block[offset:offset + sub_size]
                    last_mast = raw.rstrip(b"\x00").decode("utf-8", errors="replace")
                elif sub_type == b"DATA" and last_mast is not None:
                    if sub_size >= 8:
                        expected = struct.unpack_from("<Q", block, offset)[0]
                        result[last_mast] = expected
                    last_mast = None
                else:
                    last_mast = None

                offset += sub_size

            return result
    except (OSError, struct.error):
        return {}


def check_version_mismatched_masters(
    plugin_names: list[str],
    plugin_paths: dict[str, Path],
    data_dir: Path,
) -> dict[str, list[str]]:
    """Check for masters that are present but whose file size doesn't match
    the size recorded in the plugin header (version mismatch).

    Only meaningful for TES3 (Morrowind) plugins. Returns {} for TES4+.

    Parameters
    ----------
    plugin_names : list[str]
        Enabled plugin filenames in load order.
    plugin_paths : dict[str, Path]
        Mapping of lowercase plugin name → absolute path on disk.
    data_dir : Path
        The game's Data Files directory where masters are deployed.

    Returns
    -------
    dict[str, list[str]]
        Mapping of plugin name → list of master filenames with size mismatches.
    """
    mismatch_map: dict[str, list[str]] = {}

    for plugin_name in plugin_names:
        path = plugin_paths.get(plugin_name.lower())
        if path is None or not path.is_file():
            continue

        masters_with_sizes = read_masters_with_sizes(path)
        if not masters_with_sizes:
            continue

        mismatched: list[str] = []
        for master_name, expected_size in masters_with_sizes.items():
            # Find the master file on disk (case-insensitive)
            master_lower = master_name.lower()
            master_path: Path | None = None
            if data_dir.is_dir():
                for f in data_dir.iterdir():
                    if f.name.lower() == master_lower:
                        master_path = f
                        break
            if master_path is None or not master_path.is_file():
                continue  # Missing masters handled separately
            actual_size = master_path.stat().st_size
            if actual_size != expected_size:
                mismatched.append(master_name)

        if mismatched:
            mismatch_map[plugin_name] = mismatched

    return mismatch_map


def check_missing_masters(
    plugin_names: list[str],
    plugin_paths: dict[str, Path],
) -> dict[str, list[str]]:
    """
    Check every plugin for missing master dependencies.

    Parameters
    ----------
    plugin_names : list[str]
        All plugin filenames in the current load order (enabled or not).
    plugin_paths : dict[str, Path]
        Mapping of lowercase plugin name → absolute path on disk.

    Returns
    -------
    dict[str, list[str]]
        Mapping of plugin name → list of missing master filenames.
        Only plugins that actually have missing masters are included.
    """
    known = {name.lower() for name in plugin_names}
    missing_map: dict[str, list[str]] = {}

    for plugin_name in plugin_names:
        path = plugin_paths.get(plugin_name.lower())
        if path is None or not path.is_file():
            continue

        masters = read_masters(path)
        missing = [m for m in masters if m.lower() not in known]
        if missing:
            missing_map[plugin_name] = missing

    return missing_map


def check_late_masters(
    plugin_names: list[str],
    plugin_paths: dict[str, Path],
) -> dict[str, list[str]]:
    """
    Check for masters that are present in the load order but loaded *after*
    the plugin that requires them (master loaded after dependent).

    Parameters
    ----------
    plugin_names : list[str]
        Enabled plugin filenames in load order (index = position).
    plugin_paths : dict[str, Path]
        Mapping of lowercase plugin name → absolute path on disk.

    Returns
    -------
    dict[str, list[str]]
        Mapping of plugin name → list of master filenames that appear later
        in the load order than the plugin itself.
        Only plugins with at least one late master are included.
    """
    index_map = {name.lower(): i for i, name in enumerate(plugin_names)}
    late_map: dict[str, list[str]] = {}

    for i, plugin_name in enumerate(plugin_names):
        path = plugin_paths.get(plugin_name.lower())
        if path is None or not path.is_file():
            continue

        masters = read_masters(path)
        late = [m for m in masters if index_map.get(m.lower(), -1) > i]
        if late:
            late_map[plugin_name] = late

    return late_map
