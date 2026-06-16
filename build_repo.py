#!/usr/bin/env python3
"""Build a Kodi-format addon repository for hosting on Cloudflare Pages.

Layout produced in `dist-pages/`:
    addons.xml                      <- master manifest of all addons + versions
    addons.xml.md5                  <- checksum for Kodi to detect updates
    plugin.service.alfredbridge/
        plugin.service.alfredbridge-2.0.0.zip
    repository.alfredbridge/
        repository.alfredbridge-1.0.0.zip

The repository wrapper addon's `addon.xml` is built from its template, with
{{REPO_URL}} replaced by the configured public URL (defaults to env var
ALFRED_REPO_URL, falls back to a placeholder).

Usage:
    ALFRED_REPO_URL=https://kodi-addons-XXXX.pages.dev python3 build_repo.py
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist-pages"
ADDONS = [
    ROOT / "plugin.service.alfredbridge",
    ROOT / "repository.alfredbridge",
]
REPO_URL = os.environ.get("ALFRED_REPO_URL", "https://REPLACE_ME.pages.dev").rstrip("/")
EXCLUDE_NAMES = {"__pycache__", ".DS_Store", "addon.xml.template"}


def materialize_repository_addon():
    """Render repository.alfredbridge/addon.xml from template with the live URL."""
    tmpl = (ROOT / "repository.alfredbridge" / "addon.xml.template").read_text()
    rendered = tmpl.replace("{{REPO_URL}}", REPO_URL)
    out = ROOT / "repository.alfredbridge" / "addon.xml"
    out.write_text(rendered)


def addon_id_and_version(addon_dir: Path) -> tuple[str, str]:
    tree = ET.parse(addon_dir / "addon.xml")
    root = tree.getroot()
    return root.attrib["id"], root.attrib["version"]


def package_addon(addon_dir: Path, out_dir: Path) -> Path:
    """Package via system `zip` command so the archive has explicit directory entries
    (which some Kodi-on-Xbox extractors require). Falls back to ZipFile if zip is missing."""
    addon_id, version = addon_id_and_version(addon_dir)
    addon_out = out_dir / addon_id
    addon_out.mkdir(parents=True, exist_ok=True)
    zip_name = f"{addon_id}-{version}.zip"
    zip_path = addon_out / zip_name
    if zip_path.exists():
        zip_path.unlink()

    import shutil, subprocess
    if shutil.which("zip"):
        excludes = []
        for pattern in EXCLUDE_NAMES:
            excludes += ["-x", f"*{pattern}*"]
        excludes += ["-x", "*.pyc"]
        subprocess.run(
            ["zip", "-r", "-q", str(zip_path), addon_dir.name, *excludes],
            cwd=str(addon_dir.parent),
            check=True,
        )
    else:
        with ZipFile(zip_path, "w", ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(addon_dir):
                dirs[:] = [d for d in dirs if d not in EXCLUDE_NAMES]
                rel_dir = Path(root).relative_to(addon_dir.parent)
                zf.writestr(str(rel_dir) + "/", "")
                for f in files:
                    if f in EXCLUDE_NAMES or f.endswith((".pyc",)):
                        continue
                    src = Path(root) / f
                    zf.write(src, arcname=str(rel_dir / f))
    return zip_path


def build_addons_xml(out_dir: Path):
    """Concatenate each addon's addon.xml into a master addons.xml."""
    root = ET.Element("addons")
    for addon_dir in ADDONS:
        addon_tree = ET.parse(addon_dir / "addon.xml")
        root.append(addon_tree.getroot())
    raw = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    addons_path = out_dir / "addons.xml"
    addons_path.write_bytes(raw)
    md5 = hashlib.md5(raw).hexdigest()
    (out_dir / "addons.xml.md5").write_text(md5 + "\n")
    return addons_path


def _format_apache_index(dir_path: Path, base_path: str = "") -> str:
    """Apache-mod_autoindex-style listing that Kodi can parse to browse directories."""
    rows = []
    if base_path:
        rows.append('<a href="../">../</a>')
    for entry in sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if entry.name in (".DS_Store", "index.html"):
            continue
        name = entry.name + ("/" if entry.is_dir() else "")
        rows.append(f'<a href="{name}">{name}</a>')
    body = "\n".join(rows)
    return f"""<!doctype html>
<html>
<head><title>Index of /{base_path}</title></head>
<body>
<h1>Index of /{base_path}</h1>
<pre>
{body}
</pre>
</body>
</html>
"""


def write_directory_indexes(out_dir: Path) -> None:
    """Write Apache-style index.html in root and every subdirectory."""
    (out_dir / "index.html").write_text(_format_apache_index(out_dir, ""))
    for entry in out_dir.iterdir():
        if entry.is_dir():
            (entry / "index.html").write_text(_format_apache_index(entry, entry.name + "/"))


def write_index_html(out_dir: Path):
    """Backwards-compat shim — calls the new directory-index writer."""
    write_directory_indexes(out_dir)


def main() -> int:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    materialize_repository_addon()

    print(f"Repo URL: {REPO_URL}")
    for addon_dir in ADDONS:
        zip_path = package_addon(addon_dir, DIST)
        print(f"  packaged {zip_path.relative_to(ROOT)}")

    build_addons_xml(DIST)
    write_index_html(DIST)
    print(f"  wrote {(DIST / 'addons.xml').relative_to(ROOT)}")
    print(f"  wrote {(DIST / 'addons.xml.md5').relative_to(ROOT)}")
    print(f"Done. Deploy `{DIST.relative_to(ROOT)}/` as a Cloudflare Pages project.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
