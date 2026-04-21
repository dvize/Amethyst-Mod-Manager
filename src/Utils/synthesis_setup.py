"""
Utils/synthesis_setup.py
Prepare a standalone Wine prefix for Mutagen Synthesis.

Synthesis needs a .NET 9 SDK + .NET 10 Desktop Runtime + DigiCert root cert
+ Win11 Windows version + a handful of registry tweaks + a Bethesda install
path registry entry so it can locate the game. We do all of this in a
dedicated prefix next to the extracted Synthesis.exe so the real game prefix
stays untouched.

Per-step marker files under <pfx>/.synthesis_setup/<step>.done let re-runs
skip steps that already completed.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable

from Utils.config_paths import get_dotnet_cache_dir, get_vcredist_cache_path


# ---------------------------------------------------------------------------
# Download URLs
# ---------------------------------------------------------------------------

_DOTNET9_SDK_URL = (
    "https://builds.dotnet.microsoft.com/dotnet/Sdk/9.0.310/"
    "dotnet-sdk-9.0.310-win-x64.exe"
)
_DOTNET9_SDK_FILENAME = "dotnet-sdk-9.0.310-win-x64.exe"

_DOTNET10_DESKTOP_URL = (
    "https://builds.dotnet.microsoft.com/dotnet/WindowsDesktop/10.0.2/"
    "windowsdesktop-runtime-10.0.2-win-x64.exe"
)
_DOTNET10_DESKTOP_FILENAME = "windowsdesktop-runtime-10.0.2-win-x64.exe"

# Older desktop runtimes — some patchers target net6/7/8 and refuse to roll
# forward to 9/10. We install the latest patch of each LTS/EOL line.
_DOTNET8_DESKTOP_URL = (
    "https://builds.dotnet.microsoft.com/dotnet/WindowsDesktop/8.0.11/"
    "windowsdesktop-runtime-8.0.11-win-x64.exe"
)
_DOTNET8_DESKTOP_FILENAME = "windowsdesktop-runtime-8.0.11-win-x64.exe"

_DOTNET7_DESKTOP_URL = (
    "https://builds.dotnet.microsoft.com/dotnet/WindowsDesktop/7.0.20/"
    "windowsdesktop-runtime-7.0.20-win-x64.exe"
)
_DOTNET7_DESKTOP_FILENAME = "windowsdesktop-runtime-7.0.20-win-x64.exe"

_DOTNET6_DESKTOP_URL = (
    "https://builds.dotnet.microsoft.com/dotnet/WindowsDesktop/6.0.36/"
    "windowsdesktop-runtime-6.0.36-win-x64.exe"
)
_DOTNET6_DESKTOP_FILENAME = "windowsdesktop-runtime-6.0.36-win-x64.exe"

_DIGICERT_CERT_URL = "https://cacerts.digicert.com/DigiCertTrustedRootG4.crt.pem"
_DIGICERT_CERT_FILENAME = "DigiCertTrustedRootG4.crt.pem"

_VCREDIST_URL = "https://aka.ms/vc14/vc_redist.x64.exe"


# xEdit family — needs WinXP compat mode under Wine.
_XEDIT_EXECUTABLES = [
    "SSEEdit.exe", "SSEEdit64.exe",
    "FO4Edit.exe", "FO4Edit64.exe",
    "TES4Edit.exe", "TES4Edit64.exe",
    "xEdit64.exe",
    "SF1Edit64.exe",
    "FNVEdit.exe", "FNVEdit64.exe",
    "xFOEdit.exe", "xFOEdit64.exe",
    "xSFEEdit.exe", "xSFEEdit64.exe",
    "xTESEdit.exe", "xTESEdit64.exe",
    "FO3Edit.exe", "FO3Edit64.exe",
]

# Global DLL overrides — game/tool-provided DLLs win over Wine builtins.
_DLL_OVERRIDES = [
    "dwrite", "winmm", "version", "dxgi", "dbghelp",
    "d3d12", "wininet", "winhttp", "dinput", "dinput8",
]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _wine_bin(proton_script: Path) -> Path:
    return proton_script.parent / "files" / "bin" / "wine"


def _proton_files_dir(wine: Path) -> Path:
    # .../files/bin/wine -> .../files
    return wine.parent.parent


def build_proton_env(
    pfx: Path,
    wine: Path,
    dll_overrides: str = "mshtml=d;winemenubuilder.exe=d",
) -> dict[str, str]:
    """Build the env needed to run a Wine binary against a Proton install.

    Mirrors what ``proton run`` does so Wine can find its bundled DLLs
    (icu, vkd3d, gstreamer, …) and Linux libs without Proton's sniper
    container wrapper. Without WINEDLLPATH+LD_LIBRARY_PATH, icu.dll's forwards
    to icuuc68.dll fail and .NET WPF apps crash.
    """
    files = _proton_files_dir(wine)
    env = os.environ.copy()
    env["WINEPREFIX"] = str(pfx)
    env["WINEDEBUG"] = "-all"
    env["WINEDLLOVERRIDES"] = dll_overrides
    env.setdefault("DISPLAY", os.environ.get("DISPLAY", ":0"))

    dll_paths = [str(files / "lib" / "vkd3d"), str(files / "lib" / "wine")]
    if "WINEDLLPATH" in os.environ:
        dll_paths.append(os.environ["WINEDLLPATH"])
    env["WINEDLLPATH"] = os.pathsep.join(dll_paths)

    ld_paths = [
        str(files / "lib" / "x86_64-linux-gnu"),
        str(files / "lib" / "i386-linux-gnu"),
    ]
    if os.environ.get("LD_LIBRARY_PATH"):
        ld_paths.append(os.environ["LD_LIBRARY_PATH"])
    env["LD_LIBRARY_PATH"] = ":".join(ld_paths)
    return env


def _base_env(pfx: Path, wine: Path | None = None) -> dict[str, str]:
    """Env for running wine against our prefix.

    If *wine* is provided, include Proton's WINEDLLPATH + LD_LIBRARY_PATH so
    Wine finds its bundled DLLs (icu, vkd3d, …). All in-prefix setup steps
    must pass *wine* or installers and .NET startup will be broken inside
    the installer too.
    """
    if wine is not None:
        return build_proton_env(pfx, wine)
    env = os.environ.copy()
    env["WINEPREFIX"] = str(pfx)
    env["WINEDEBUG"] = "-all"
    env["WINEDLLOVERRIDES"] = "mshtml=d;winemenubuilder.exe=d"
    env.setdefault("DISPLAY", os.environ.get("DISPLAY", ":0"))
    return env


def _markers_dir(pfx: Path) -> Path:
    d = pfx / ".synthesis_setup"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _is_done(pfx: Path, step: str) -> bool:
    return (_markers_dir(pfx) / f"{step}.done").is_file()


def _mark_done(pfx: Path, step: str) -> None:
    (_markers_dir(pfx) / f"{step}.done").write_text("ok\n")


def _posix_to_wine_path(p: Path) -> str:
    """Convert a POSIX path to Wine's Z:-drive form with trailing backslash.

    /home/deck/.../Skyrim Special Edition/  ->  Z:\\home\\deck\\...\\Skyrim Special Edition\\
    """
    s = str(p).replace("/", "\\")
    if not s.endswith("\\"):
        s += "\\"
    return "Z:" + s


def _download_if_missing(url: str, dest: Path, log: Callable[[str], None]) -> bool:
    if dest.is_file() and dest.stat().st_size > 0:
        log(f"  cached: {dest.name}")
        return True
    log(f"  downloading {dest.name} …")
    try:
        urllib.request.urlretrieve(url, dest)
    except Exception as exc:
        log(f"  download failed: {exc}")
        return False
    return True


# ---------------------------------------------------------------------------
# Setup steps
# ---------------------------------------------------------------------------

def _ensure_prefix(
    pfx: Path,
    wine: Path,
    log: Callable[[str], None],
) -> bool:
    """Create the prefix with `wineboot -i` if it doesn't already exist."""
    if (pfx / "system.reg").is_file():
        return True

    pfx.mkdir(parents=True, exist_ok=True)
    log("Creating Wine prefix (this can take a minute on first run) …")
    result = subprocess.run(
        [str(wine), "wineboot", "-i"],
        env=_base_env(pfx, wine),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        log(f"  wineboot exited with {result.returncode}: {result.stderr[:200]}")
        return False
    log("  prefix created.")
    return True


def _step_dotnet9_sdk(pfx: Path, wine: Path, log: Callable[[str], None]) -> bool:
    if _is_done(pfx, "dotnet9_sdk"):
        log("  .NET 9 SDK already installed, skipping.")
        return True
    installer = get_dotnet_cache_dir() / _DOTNET9_SDK_FILENAME
    if not _download_if_missing(_DOTNET9_SDK_URL, installer, log):
        return False
    log("Installing .NET 9 SDK (this can take several minutes) …")
    result = subprocess.run(
        [str(wine), str(installer), "/install", "/quiet", "/norestart"],
        env=_base_env(pfx, wine),
        capture_output=True,
        text=True,
        timeout=900,
    )
    if result.returncode not in (0, 3010):
        log(f"  .NET 9 SDK installer exited with {result.returncode}")
        return False
    _mark_done(pfx, "dotnet9_sdk")
    log("  .NET 9 SDK installed.")
    return True


def _step_dotnet10_desktop(pfx: Path, wine: Path, log: Callable[[str], None]) -> bool:
    if _is_done(pfx, "dotnet10_desktop"):
        log("  .NET 10 Desktop Runtime already installed, skipping.")
        return True
    installer = get_dotnet_cache_dir() / _DOTNET10_DESKTOP_FILENAME
    if not _download_if_missing(_DOTNET10_DESKTOP_URL, installer, log):
        return False
    log("Installing .NET 10 Desktop Runtime …")
    result = subprocess.run(
        [str(wine), str(installer), "/install", "/quiet", "/norestart"],
        env=_base_env(pfx, wine),
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode not in (0, 3010):
        log(f"  .NET 10 Desktop Runtime installer exited with {result.returncode}")
        return False
    _mark_done(pfx, "dotnet10_desktop")
    log("  .NET 10 Desktop Runtime installed.")
    return True


def _install_desktop_runtime(
    pfx: Path,
    wine: Path,
    log: Callable[[str], None],
    *,
    marker: str,
    url: str,
    filename: str,
    label: str,
) -> bool:
    if _is_done(pfx, marker):
        log(f"  {label} already installed, skipping.")
        return True
    installer = get_dotnet_cache_dir() / filename
    if not _download_if_missing(url, installer, log):
        return False
    log(f"Installing {label} …")
    result = subprocess.run(
        [str(wine), str(installer), "/install", "/quiet", "/norestart"],
        env=_base_env(pfx, wine),
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode not in (0, 3010):
        log(f"  {label} installer exited with {result.returncode}")
        return False
    _mark_done(pfx, marker)
    log(f"  {label} installed.")
    return True


def _step_dotnet8_desktop(pfx: Path, wine: Path, log: Callable[[str], None]) -> bool:
    return _install_desktop_runtime(
        pfx, wine, log,
        marker="dotnet8_desktop",
        url=_DOTNET8_DESKTOP_URL,
        filename=_DOTNET8_DESKTOP_FILENAME,
        label=".NET 8 Desktop Runtime",
    )


def _step_dotnet7_desktop(pfx: Path, wine: Path, log: Callable[[str], None]) -> bool:
    return _install_desktop_runtime(
        pfx, wine, log,
        marker="dotnet7_desktop",
        url=_DOTNET7_DESKTOP_URL,
        filename=_DOTNET7_DESKTOP_FILENAME,
        label=".NET 7 Desktop Runtime",
    )


def _step_dotnet6_desktop(pfx: Path, wine: Path, log: Callable[[str], None]) -> bool:
    return _install_desktop_runtime(
        pfx, wine, log,
        marker="dotnet6_desktop",
        url=_DOTNET6_DESKTOP_URL,
        filename=_DOTNET6_DESKTOP_FILENAME,
        label=".NET 6 Desktop Runtime",
    )


def _step_digicert_root(pfx: Path, wine: Path, log: Callable[[str], None]) -> bool:
    if _is_done(pfx, "digicert_root"):
        log("  DigiCert root cert already imported, skipping.")
        return True
    cert = get_dotnet_cache_dir() / _DIGICERT_CERT_FILENAME
    if not _download_if_missing(_DIGICERT_CERT_URL, cert, log):
        return False
    log("Importing DigiCert Trusted Root G4 into Wine cert store …")
    result = subprocess.run(
        [str(wine), "certutil", "-addstore", "Root", str(cert)],
        env=_base_env(pfx, wine),
        capture_output=True,
        text=True,
        timeout=60,
    )
    # certutil often returns non-zero when the cert already exists — treat
    # that as success and only log stderr for visibility.
    if result.returncode != 0:
        log(f"  certutil exited with {result.returncode} (likely already present)")
    _mark_done(pfx, "digicert_root")
    log("  DigiCert root cert imported.")
    return True


def _step_win11_version(pfx: Path, wine: Path, log: Callable[[str], None]) -> bool:
    """Set Windows version to Win11 directly via registry.

    Mirrors what ``winetricks -q win11`` does but avoids its wineserver-on-PATH
    dependency (Proton's wineserver isn't exported globally).
    Values sourced from winetricks' w_set_winver function.
    """
    if _is_done(pfx, "win11_version"):
        log("  Windows version already set, skipping.")
        return True
    log("Setting Windows version to Windows 11 …")

    # HKLM\Software\Microsoft\Windows NT\CurrentVersion
    updates = [
        (r"HKLM\Software\Microsoft\Windows NT\CurrentVersion",
         "CurrentBuild", "REG_SZ", "22000"),
        (r"HKLM\Software\Microsoft\Windows NT\CurrentVersion",
         "CurrentBuildNumber", "REG_SZ", "22000"),
        (r"HKLM\Software\Microsoft\Windows NT\CurrentVersion",
         "CurrentVersion", "REG_SZ", "10.0"),
        (r"HKLM\Software\Microsoft\Windows NT\CurrentVersion",
         "ProductName", "REG_SZ", "Windows 10 Pro"),
        (r"HKLM\Software\Microsoft\Windows NT\CurrentVersion",
         "CSDVersion", "REG_SZ", ""),
        # HKCU\Software\Wine — Wine's own version selector
        (r"HKCU\Software\Wine", "Version", "REG_SZ", "win11"),
    ]

    env = _base_env(pfx, wine)
    all_ok = True
    for key, name, rtype, value in updates:
        args = [str(wine), "reg", "add", key, "/v", name, "/t", rtype, "/f"]
        if value:
            args += ["/d", value]
        result = subprocess.run(
            args, env=env, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            log(f"  reg add {name} failed: {result.stderr[:200].strip()}")
            all_ok = False

    # Remove the CSDVersion subkey (Wine sets it when version < win10; winetricks
    # deletes it for win10+). Non-fatal if it doesn't exist.
    subprocess.run(
        [str(wine), "reg", "delete",
         r"HKLM\System\CurrentControlSet\Control\Windows",
         "/v", "CSDVersion", "/f"],
        env=env, capture_output=True, text=True, timeout=30,
    )

    if all_ok:
        _mark_done(pfx, "win11_version")
        log("  Windows version set to Win11.")
    else:
        log("  Win11 version set with some errors (non-fatal).")
    return all_ok


def _build_reg_blob() -> str:
    lines = ["Windows Registry Editor Version 5.00", ""]

    for exe in _XEDIT_EXECUTABLES:
        lines.append(f"[HKEY_CURRENT_USER\\Software\\Wine\\AppDefaults\\{exe}]")
        lines.append('"Version"="winxp"')
        lines.append("")

    lines.append(
        "[HKEY_CURRENT_USER\\Software\\Wine\\AppDefaults\\"
        "Pandora Behaviour Engine+.exe\\X11 Driver]"
    )
    lines.append('"Decorated"="N"')
    lines.append("")

    lines.append("[HKEY_CURRENT_USER\\Software\\Wine\\X11 Driver]")
    lines.append('"UseTakeFocus"="N"')
    lines.append("")

    lines.append("[HKEY_CURRENT_USER\\Software\\Wine\\DllOverrides]")
    for dll in _DLL_OVERRIDES:
        lines.append(f'"{dll}"="native,builtin"')
    lines.append("")

    return "\r\n".join(lines)


def _step_regedit(pfx: Path, wine: Path, log: Callable[[str], None]) -> bool:
    if _is_done(pfx, "regedit_v2"):
        log("  Registry patches already applied, skipping.")
        return True
    log("Applying registry patches (xEdit compat, DLL overrides, X11 focus) …")
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".reg", delete=False, encoding="utf-8",
    ) as tf:
        tf.write(_build_reg_blob())
        reg_path = tf.name
    try:
        result = subprocess.run(
            [str(wine), "regedit", reg_path],
            env=_base_env(pfx, wine),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            log(f"  wine regedit exited with {result.returncode}: {result.stderr[:200].strip()}")
            return False
    finally:
        try:
            os.unlink(reg_path)
        except OSError:
            pass
    _mark_done(pfx, "regedit_v2")
    log("  Registry patches applied.")
    return True


def _step_game_path(
    pfx: Path,
    wine: Path,
    game_path: Path,
    registry_game_name: str,
    log: Callable[[str], None],
) -> bool:
    """Register the game's install path under HKLM so Synthesis discovers it.

    *registry_game_name* is the Bethesda Softworks subkey Mutagen probes —
    e.g. "Skyrim Special Edition", "Fallout4", "Oblivion", "Starfield".
    Changing this value invalidates the previous marker so re-runs with a
    different game pick up the new path.
    """
    marker = f"game_path_{registry_game_name}".replace(" ", "_")
    if _is_done(pfx, marker):
        log("  Game install path already registered, skipping.")
        return True

    wine_value = _posix_to_wine_path(game_path)
    key = (
        r"HKLM\Software\Wow6432Node\Bethesda Softworks"
        + "\\" + registry_game_name
    )
    log(f"Registering {registry_game_name} install path: {wine_value}")
    result = subprocess.run(
        [
            str(wine), "reg", "add", key,
            "/v", "Installed Path",
            "/t", "REG_SZ",
            "/d", wine_value,
            "/f",
        ],
        env=_base_env(pfx, wine),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        log(f"  reg add exited with {result.returncode}: {result.stderr[:200]}")
        return False
    _mark_done(pfx, marker)
    log("  Game path registered.")
    return True


def _step_fonts(pfx: Path, wine: Path, log: Callable[[str], None]) -> bool:
    """Symlink Proton's bundled fonts into the prefix's Fonts dir.

    Proton ships real Arial/Tahoma/Times/Courier/etc. under
    ``files/share/fonts`` + ``files/share/wine/fonts`` and, when a game is
    launched through Steam, its prefix-init links them into
    ``drive_c/windows/Fonts``. Our wineboot-only prefix skips that step, so
    WPF's text shaping finds no typefaces and FailFasts the first time it
    tries to measure a TextBlock. Reproducing the same symlink layout is
    enough to make Synthesis render.
    """
    if _is_done(pfx, "fonts"):
        log("  Fonts already linked, skipping.")
        return True

    files = _proton_files_dir(wine)
    share_fonts = files / "share" / "fonts"
    wine_fonts = files / "share" / "wine" / "fonts"
    if not wine_fonts.is_dir():
        log(f"  Proton wine fonts dir missing at {wine_fonts}.")
        return False

    dst = pfx / "drive_c" / "windows" / "Fonts"
    dst.mkdir(parents=True, exist_ok=True)

    # Layout matches what Proton creates for a real game prefix: MS-licensed
    # replacements from share/fonts override the bundled Wine fonts where they
    # overlap (arial, courbd, cour, times, tahoma* come from share/fonts).
    overrides = {
        "arial.ttf", "arialbd.ttf", "courbd.ttf", "cour.ttf",
        "georgia.ttf", "malgun.ttf", "micross.ttf", "msgothic.ttc",
        "msyh.ttf", "nirmala.ttf", "simsun.ttc", "times.ttf",
    }

    linked = 0
    # First pass: bundled Wine fonts.
    if wine_fonts.is_dir():
        for f in wine_fonts.iterdir():
            if f.is_file():
                target = dst / f.name
                if target.is_symlink() or target.exists():
                    target.unlink()
                target.symlink_to(f)
                linked += 1

    # Second pass: MS replacements override.
    if share_fonts.is_dir():
        for name in overrides:
            src = share_fonts / name
            if src.is_file():
                target = dst / name
                if target.is_symlink() or target.exists():
                    target.unlink()
                target.symlink_to(src)

    _mark_done(pfx, "fonts")
    log(f"  Fonts linked ({linked} bundled + MS replacements).")
    return True


def _step_vcredist(pfx: Path, wine: Path, log: Callable[[str], None]) -> bool:
    """Install Visual C++ Redistributable (x64) into the prefix.

    WPF apps under Wine can fail in SplashScreen CreateWindowEx with
    error 1813 ("Resource type not found") when MSVC runtime DLLs are missing.
    """
    if _is_done(pfx, "vcredist"):
        log("  VC++ Redistributable already installed, skipping.")
        return True
    installer = get_vcredist_cache_path()
    if not _download_if_missing(_VCREDIST_URL, installer, log):
        return False
    log("Installing Visual C++ Redistributable (x64) …")
    result = subprocess.run(
        [str(wine), str(installer), "/install", "/quiet", "/norestart"],
        env=_base_env(pfx, wine),
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode not in (0, 1638, 3010):
        # 1638 = already-present newer version, treat as success.
        log(f"  vc_redist exited with {result.returncode}")
        return False
    _mark_done(pfx, "vcredist")
    log("  VC++ Redistributable installed.")
    return True


def _step_nuget_config(pfx: Path, wine: Path, log: Callable[[str], None]) -> bool:
    """Write NuGet.Config with trustedSigners (allowUntrustedRoot) + accept mode.

    Mutagen's deps include 2020-era packages whose authors used timestamping
    certs that have since rolled past their validity window. Default ``require``
    mode rejects these with NU3037 (primary signature expired) and NU3028
    (timestamping cert chain untrusted). ``signatureValidationMode=accept``
    alone is not enough in .NET 9 — expired-timestamp checks still fire.

    The supported escape hatch is ``<trustedSigners>`` with
    ``allowUntrustedRoot="true"``: NuGet treats listed author/repository certs
    as trusted even when their chain doesn't validate, which covers expired
    timestamping intermediates. The fingerprints below are nuget.org's real
    repository cert + Microsoft's author cert.
    """
    if _is_done(pfx, "nuget_config_v6"):
        return True
    cfg = (
        pfx / "drive_c" / "users" / "steamuser"
        / "AppData" / "Roaming" / "NuGet" / "NuGet.Config"
    )
    cfg.parent.mkdir(parents=True, exist_ok=True)
    # Repository (nuget.org) + author (microsoft) trust with
    # allowUntrustedRoot="true" so Wine's incomplete root store + expired
    # timestamping chains don't reject packages. Author fingerprints cover
    # the handful of code-signing certs Microsoft has used on nuget.org; the
    # repository block catches everything else pushed to nuget.org.
    content = (
        '\ufeff<?xml version="1.0" encoding="utf-8"?>\n'
        '<configuration>\n'
        '  <packageSources>\n'
        '    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" protocolVersion="3" />\n'
        '  </packageSources>\n'
        '  <config>\n'
        '    <add key="signatureValidationMode" value="accept" />\n'
        '  </config>\n'
        '  <trustedSigners>\n'
        '    <author name="microsoft">\n'
        '      <certificate fingerprint="3F9001EA83C560D712C24CF213C3D312CB3BFF51EE89435D3430BD06B5D0EECE" hashAlgorithm="SHA256" allowUntrustedRoot="true" />\n'
        '      <certificate fingerprint="AA12DA22A49BCE7D5C1AE64CC1F3D892F150DA76140F210ABD2CBFFCA2C18A27" hashAlgorithm="SHA256" allowUntrustedRoot="true" />\n'
        '      <certificate fingerprint="566A31882BE208BE4422F7CFD66ED09F5D4524A5994F50CCC8B05EC0528C1353" hashAlgorithm="SHA256" allowUntrustedRoot="true" />\n'
        '      <certificate fingerprint="8A17C2B974AD64F4A47982E292D9F89DCC10F0E2AE9C09CBC38C180AA94C9CBA" hashAlgorithm="SHA256" allowUntrustedRoot="true" />\n'
        '      <certificate fingerprint="51044706BD237B91B89B781337E6D62656C69F0FCFFBE8E43741367948127862" hashAlgorithm="SHA256" allowUntrustedRoot="true" />\n'
        '      <certificate fingerprint="9DC17888B5CFAD98B3CB35C1994E96227F061675955B6C5B0C842BE5B89E5885" hashAlgorithm="SHA256" allowUntrustedRoot="true" />\n'
        '      <certificate fingerprint="AFCEA55DD42024B8B1D07F6E5D5DD0E4A0DAF12A78AEF80C4D7C11880BE21E45" hashAlgorithm="SHA256" allowUntrustedRoot="true" />\n'
        '    </author>\n'
        '    <repository name="nuget.org" serviceIndex="https://api.nuget.org/v3/index.json">\n'
        '      <certificate fingerprint="0E5F38F57DC1BCC806D8494F4F90FBCEDD988B46760709CBEEC6F4219AA6157D" hashAlgorithm="SHA256" allowUntrustedRoot="true" />\n'
        '      <certificate fingerprint="5A2901D6ADA3D18260B9C6DFE2133C95D74B9EEF6AE0E5DC334C8454D1477DF4" hashAlgorithm="SHA256" allowUntrustedRoot="true" />\n'
        '      <certificate fingerprint="1F4B311D9ACC115C8DC8018B5A49E00FCE6DA8E2855F9F014CA6F34570BC482D" hashAlgorithm="SHA256" allowUntrustedRoot="true" />\n'
        '    </repository>\n'
        '  </trustedSigners>\n'
        '</configuration>\n'
    )
    cfg.write_text(content, encoding="utf-8")
    _mark_done(pfx, "nuget_config_v6")
    log("  NuGet.Config written with trustedSigners (allowUntrustedRoot).")
    return True


def _step_mscoree_cleanup(pfx: Path, wine: Path, log: Callable[[str], None]) -> bool:
    if _is_done(pfx, "mscoree_cleanup"):
        return True
    subprocess.run(
        [
            str(wine), "reg", "delete",
            r"HKCU\Software\Wine\DllOverrides",
            "/v", "*mscoree", "/f",
        ],
        env=_base_env(pfx, wine),
        capture_output=True,
        text=True,
        timeout=30,
    )
    _mark_done(pfx, "mscoree_cleanup")
    return True


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def setup_synthesis_prefix(
    synthesis_dir: Path,
    proton_script: Path,
    game_path: Path,
    log_fn: Callable[[str], None],
    prefix_parent: Path | None = None,
    registry_game_name: str = "Skyrim Special Edition",
) -> bool:
    """Prepare the Synthesis prefix. Returns True on full success.

    *prefix_parent* is the compatdata-style dir that contains ``pfx/``.
    Defaults to ``<synthesis_dir>/prefix`` so the Wine environment lives in
    its own subfolder and can be wiped without touching Synthesis.exe.

    *registry_game_name* is the ``HKLM\\Software\\Wow6432Node\\Bethesda
    Softworks\\<name>`` subkey Mutagen probes. Defaults to Skyrim SE for
    back-compat.
    """
    if prefix_parent is None:
        prefix_parent = synthesis_dir / "prefix"
    prefix_parent.mkdir(parents=True, exist_ok=True)
    pfx = prefix_parent / "pfx"

    wine = _wine_bin(proton_script)
    if not wine.is_file():
        log_fn(f"Wine binary not found at {wine}")
        return False

    if not _ensure_prefix(pfx, wine, log_fn):
        return False

    ok = True
    ok &= _step_mscoree_cleanup(pfx, wine, log_fn)
    ok &= _step_win11_version(pfx, wine, log_fn)
    ok &= _step_vcredist(pfx, wine, log_fn)
    ok &= _step_dotnet9_sdk(pfx, wine, log_fn)
    ok &= _step_dotnet10_desktop(pfx, wine, log_fn)
    ok &= _step_dotnet8_desktop(pfx, wine, log_fn)
    ok &= _step_dotnet7_desktop(pfx, wine, log_fn)
    ok &= _step_dotnet6_desktop(pfx, wine, log_fn)
    ok &= _step_digicert_root(pfx, wine, log_fn)
    ok &= _step_regedit(pfx, wine, log_fn)
    ok &= _step_fonts(pfx, wine, log_fn)
    ok &= _step_nuget_config(pfx, wine, log_fn)
    ok &= _step_game_path(pfx, wine, game_path, registry_game_name, log_fn)

    if ok:
        log_fn("Synthesis prefix ready.")
    else:
        log_fn("Synthesis prefix setup finished with errors — see log above.")
    return ok
