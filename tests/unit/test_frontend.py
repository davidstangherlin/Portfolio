"""The React and TypeScript pages (frontend/, ADR-018) are built into
web/dist, which is committed so the owner's PC needs no Node.js. These
tests make sure the committed bundle is there, loaded by the page, and
built from the sources as they stand (frontend/scripts/build-info.mjs
writes the fingerprint; it is worked out the same way here). The type
check and component tests run too when Node.js and frontend/node_modules
are present."""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
DIST = ROOT / "web" / "dist"
CONFIG_FILES = ["package.json", "package-lock.json", "vite.config.ts", "tsconfig.json"]


def source_fingerprint() -> tuple[str, int]:
    files = list(CONFIG_FILES)
    files += [p.relative_to(FRONTEND).as_posix() for p in (FRONTEND / "src").rglob("*")
              if p.is_file() and not p.name.endswith((".test.ts", ".test.tsx"))]
    files.sort()
    digest = hashlib.sha256()
    for f in files:
        digest.update(f.encode() + b"\0")
        digest.update((FRONTEND / f).read_text(encoding="utf-8").replace("\r\n", "\n").encode() + b"\0")
    return digest.hexdigest(), len(files)


def test_bundle_is_committed_and_loaded_before_app_js():
    assert (DIST / "sift-ui.js").stat().st_size > 10_000
    page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert '<script src="/static/dist/sift-ui.js"></script>' in page
    assert page.index("/static/dist/sift-ui.js") < page.index("/static/app.js")


def test_bundle_was_built_from_current_sources():
    info = json.loads((DIST / "build-info.json").read_text(encoding="utf-8"))
    sources, count = source_fingerprint()
    assert (info["sources"], info["files"]) == (sources, count), (
        "frontend/ changed since web/dist was built: run `npm run build` in frontend/ and commit web/dist")


def test_every_island_used_by_app_js_is_registered():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    main = (FRONTEND / "src" / "main.tsx").read_text(encoding="utf-8")
    used = set(re.findall(r'island\("([A-Za-z]+)"', app))
    assert used, "app.js mounts no islands"
    registered = set(re.search(r"const ISLANDS[^=]*=\s*\{([^}]*)\}", main).group(1).replace(" ", "").split(","))
    assert used <= registered


def test_library_versions_are_pinned_exactly():
    pkg = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    for name, version in {**pkg["dependencies"], **pkg["devDependencies"]}.items():
        assert version[0].isdigit(), f"{name} {version}: pin an exact version (ADR-018)"


needs_node = pytest.mark.skipif(shutil.which("npx") is None or not (FRONTEND / "node_modules").is_dir(),
                                reason="Node.js or frontend/node_modules not installed")


@needs_node
def test_typescript_type_check():
    result = subprocess.run(["npx", "tsc", "--noEmit"], cwd=FRONTEND, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr


@needs_node
def test_component_tests():
    result = subprocess.run(["npx", "vitest", "run"], cwd=FRONTEND, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
