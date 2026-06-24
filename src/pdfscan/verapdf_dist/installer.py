"""Bundled veraPDF auto-download / headless-install / locate helpers.

veraPDF ships as an `IzPack <https://izpack.org/>`_ 5 installer (a self-contained
``verapdf-installer.zip`` containing a launcher script and a fat installer jar).
There is no plain "unzip and run" distribution, so :func:`ensure_verapdf`
downloads the installer, writes an IzPack *auto-install* XML descriptor, and runs
the installer headlessly to lay down a runnable ``verapdf`` CLI under
``settings.verapdf_dir``.

The auto-install XML below was derived from the installer's own serialized
IzPack resources (``resources/panelsOrder`` and ``resources/packs.info`` inside
``verapdf-izpack-installer-<ver>.jar``). The panel ids are, in order:
``welcome`` (HTMLHelloPanel), ``install_dir`` (TargetPanel),
``sdk_pack_select`` (PacksPanel), ``install`` (InstallPanel) and ``finish``
(FinishPanel). The available packs are ``veraPDF GUI``, ``veraPDF CLI``,
``veraPDF Documentation`` and ``veraPDF Sample Plugins``; the *CLI* pack is the
one that installs ``$INSTALL_PATH/verapdf.bat`` (Windows) / ``$INSTALL_PATH/verapdf``
(POSIX).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pdfscan.config import Settings

__all__ = [
    "installed_verapdf_path",
    "resolve_verapdf",
    "ensure_verapdf",
]

# IzPack panel ids (from resources/panelsOrder) and pack names (from
# resources/packs.info). Selecting the "veraPDF CLI" pack is what gives us a
# runnable ``verapdf``/``verapdf.bat``; the GUI/docs/plugin packs are optional.
_PACKS_PANEL_ID = "sdk_pack_select"
_CLI_PACK_NAME = "veraPDF CLI"


def _verapdf_exe_name() -> str:
    """File name of the installed veraPDF launcher for the current OS."""
    return "verapdf.bat" if os.name == "nt" else "verapdf"


def installed_verapdf_path(settings: Settings) -> Path | None:
    """Return the installed veraPDF launcher under ``settings.verapdf_dir``.

    On Windows that is ``<verapdf_dir>/verapdf.bat``; on POSIX it is
    ``<verapdf_dir>/verapdf``. Returns ``None`` when the file is absent.
    """
    candidate = settings.verapdf_dir / _verapdf_exe_name()
    return candidate if candidate.is_file() else None


def resolve_verapdf(settings: Settings) -> str | None:
    """Locate a usable veraPDF executable, honouring configuration precedence.

    Precedence:
      1. ``settings.verapdf_command`` (explicit env/yaml path), if it exists.
      2. :func:`installed_verapdf_path` (the bundled install).
      3. ``shutil.which("verapdf")`` (a veraPDF already on ``PATH``).

    Returns the path as a string, or ``None`` if nothing is found.
    """
    explicit = settings.verapdf_command
    if explicit:
        explicit_path = Path(explicit)
        if explicit_path.is_file():
            return str(explicit_path)
        # An explicit command that is resolvable on PATH (e.g. a bare name).
        on_path = shutil.which(explicit)
        if on_path:
            return on_path

    installed = installed_verapdf_path(settings)
    if installed is not None:
        return str(installed)

    found = shutil.which("verapdf")
    if found:
        return found

    return None


def _java_version_line() -> str | None:
    """Return java's reported version line (java prints it to stderr), or None."""
    try:
        proc = subprocess.run(
            ["java", "-version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (proc.stderr or "") + (proc.stdout or "")
    for line in output.splitlines():
        if line.strip():
            return line.strip()
    return None


def _download_installer(settings: Settings, dest: Path) -> Path:
    """Download the veraPDF installer zip from ``verapdf.installer_url`` to *dest*."""
    url = settings.get("verapdf.installer_url")
    if not url:
        raise RuntimeError(
            "No veraPDF installer URL configured (verapdf.installer_url). "
            "Set it in config/settings.yaml or pass installer_zip explicitly."
        )
    # Imported lazily so unit tests need not have requests' network stack engaged.
    import requests

    timeout = int(settings.get("verapdf.timeout", 180))
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(url, stream=True, timeout=timeout) as resp:
            resp.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        fh.write(chunk)
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(
            f"Failed to download veraPDF installer from {url}: {exc}"
        ) from exc
    return dest


def _extract_installer(zip_path: Path, dest_dir: Path) -> Path:
    """Extract the installer zip and return the directory holding the installer jar.

    The official zip extracts to a single ``verapdf-greenfield-<ver>/`` folder
    containing ``verapdf-izpack-installer-<ver>.jar`` and launcher scripts. We
    locate the directory that actually contains the ``*-izpack-installer-*.jar``.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest_dir)
    except (zipfile.BadZipFile, OSError) as exc:
        raise RuntimeError(
            f"veraPDF installer archive at {zip_path} could not be extracted: {exc}"
        ) from exc

    jars = sorted(dest_dir.rglob("*izpack-installer*.jar"))
    if not jars:
        raise RuntimeError(
            f"No IzPack installer jar found inside {zip_path} after extraction. "
            "The archive layout may have changed."
        )
    return jars[0]


def _auto_install_xml(install_path: Path) -> str:
    """Build the IzPack auto-install descriptor selecting the veraPDF CLI pack.

    ``install_path`` must be absolute. We select only the CLI pack (which lays
    down ``verapdf``/``verapdf.bat`` plus the validation engine it depends on);
    the GUI/docs/plugin packs are explicitly deselected to keep the install lean.
    """
    install_str = str(install_path)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        "<AutomatedInstallation langpack=\"eng\">\n"
        '  <com.izforge.izpack.panels.htmlhello.HTMLHelloPanel id="welcome"/>\n'
        '  <com.izforge.izpack.panels.target.TargetPanel id="install_dir">\n'
        f"    <installpath>{install_str}</installpath>\n"
        "  </com.izforge.izpack.panels.target.TargetPanel>\n"
        f'  <com.izforge.izpack.panels.packs.PacksPanel id="{_PACKS_PANEL_ID}">\n'
        '    <pack index="0" name="veraPDF GUI" selected="false"/>\n'
        '    <pack index="1" name="veraPDF CLI" selected="true"/>\n'
        '    <pack index="2" name="veraPDF Documentation" selected="false"/>\n'
        '    <pack index="3" name="veraPDF Sample Plugins" selected="false"/>\n'
        "  </com.izforge.izpack.panels.packs.PacksPanel>\n"
        '  <com.izforge.izpack.panels.install.InstallPanel id="install"/>\n'
        '  <com.izforge.izpack.panels.finish.FinishPanel id="finish"/>\n'
        "</AutomatedInstallation>\n"
    )


def _run_izpack_installer(installer_jar: Path, auto_xml: Path, timeout: int) -> None:
    """Run the IzPack installer jar headlessly with the auto-install descriptor."""
    try:
        proc = subprocess.run(
            ["java", "-jar", str(installer_jar), str(auto_xml)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Java was not found on PATH. veraPDF requires a Java 8+ runtime. "
            "Install a JRE/JDK and ensure `java` is on your PATH, then re-run "
            "`pdfscan setup-verapdf`."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"veraPDF installer timed out after {timeout}s. "
            "Increase verapdf.timeout in config/settings.yaml and retry."
        ) from exc

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        raise RuntimeError(
            "veraPDF IzPack installer failed "
            f"(exit code {proc.returncode}).\n"
            f"stdout:\n{stdout[-2000:]}\n"
            f"stderr:\n{stderr[-2000:]}"
        )


def _verify_verapdf(exe: Path, timeout: int) -> str:
    """Run ``<exe> --version`` and return the version output; raise on failure."""
    try:
        proc = subprocess.run(
            [str(exe), "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            f"Installed veraPDF at {exe} could not be executed: {exc}"
        ) from exc
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(
            f"Installed veraPDF at {exe} exited with code {proc.returncode}. "
            f"stderr: {stderr[-1000:]!r}"
        )
    return (proc.stdout or proc.stderr or "").strip()


def ensure_verapdf(
    settings: Settings,
    *,
    force: bool = False,
    installer_zip: str | None = None,
) -> str:
    """Ensure a runnable veraPDF exists, installing it if necessary.

    If :func:`resolve_verapdf` already finds one and ``force`` is ``False``, that
    path is returned immediately. Otherwise the installer zip is obtained (from
    ``installer_zip`` if given, else downloaded from ``verapdf.installer_url``),
    extracted, and run headlessly via an IzPack auto-install descriptor targeting
    the absolute ``settings.verapdf_dir``. The installed launcher is verified with
    ``--version`` and its path returned.

    Raises:
        RuntimeError: if Java is missing, the download/extract fails, or the
            install does not produce a working veraPDF (the message includes
            actionable guidance and any captured stderr).
    """
    if not force:
        existing = resolve_verapdf(settings)
        if existing:
            return existing

    java_line = _java_version_line()
    if java_line is None:
        raise RuntimeError(
            "Java was not found (or `java -version` failed). veraPDF requires a "
            "Java 8+ runtime. Install a JRE/JDK, ensure `java` is on your PATH, "
            "then re-run `pdfscan setup-verapdf`."
        )

    timeout = int(settings.get("verapdf.timeout", 180))
    install_dir = settings.verapdf_dir.resolve()
    temp_root = settings.temp_dir
    temp_root.mkdir(parents=True, exist_ok=True)

    work_dir = Path(tempfile.mkdtemp(prefix="verapdf-install-", dir=str(temp_root)))
    try:
        if installer_zip is not None:
            zip_path = Path(installer_zip)
            if not zip_path.is_absolute():
                zip_path = settings.resolve_path(zip_path)
            if not zip_path.is_file():
                raise RuntimeError(
                    f"installer_zip {zip_path} does not exist."
                )
        else:
            zip_path = _download_installer(settings, work_dir / "verapdf-installer.zip")

        extract_dir = work_dir / "extracted"
        installer_jar = _extract_installer(zip_path, extract_dir)

        install_dir.parent.mkdir(parents=True, exist_ok=True)

        auto_xml = work_dir / "auto-install.xml"
        auto_xml.write_text(_auto_install_xml(install_dir), encoding="utf-8")

        _run_izpack_installer(installer_jar, auto_xml, timeout)

        exe = installed_verapdf_path(settings)
        if exe is None:
            raise RuntimeError(
                "veraPDF installer completed but no "
                f"{_verapdf_exe_name()} was found under {install_dir}. "
                "The selected IzPack pack may not have produced the CLI launcher."
            )

        _verify_verapdf(exe, timeout)
        return str(exe)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
