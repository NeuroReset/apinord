import importlib
import importlib.util
import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PYZ_ROOT = ROOT / "PYZ.pyz_extracted"
EXTERNAL_ASSETS_ROOT = Path(r"C:\Users\acer\Desktop\zpi\apilocal 1403")


def _first_existing(*candidates: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _resource_path(relative_path: str) -> str:
    return str(
        _first_existing(
            EXTERNAL_ASSETS_ROOT / relative_path,
            ROOT / relative_path,
            PYZ_ROOT / relative_path,
        )
    )


def _resolve_data_path(filename: str) -> str:
    return str(
        _first_existing(
            EXTERNAL_ASSETS_ROOT / filename,
            ROOT / filename,
            PYZ_ROOT / filename,
        )
    )


def _sync_runtime_file(filename: str) -> None:
    external = EXTERNAL_ASSETS_ROOT / filename
    local = ROOT / filename
    if not external.exists():
        return
    if local.exists() and local.read_bytes() == external.read_bytes():
        return
    shutil.copy2(external, local)


def _base_dirs() -> list[str]:
    dirs = [str(EXTERNAL_ASSETS_ROOT), str(ROOT), str(PYZ_ROOT)]
    seen = []
    for item in dirs:
        if item not in seen:
            seen.append(item)
    return seen


def _load_pyc_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Falha ao carregar modulo: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    _sync_runtime_file("proxy.txt")
    os.chdir(ROOT)
    sys.path[:0] = [str(ROOT), str(PYZ_ROOT)]

    core_utils = _load_pyc_module("core.utils", PYZ_ROOT / "core" / "utils.pyc")
    token_manager = _load_pyc_module(
        "core.token_manager", PYZ_ROOT / "core" / "token_manager.pyc"
    )

    core_utils.resource_path = _resource_path
    core_utils._resolve_data_path = _resolve_data_path
    core_utils.PROXY_FILE = str(EXTERNAL_ASSETS_ROOT / "proxy.txt")
    core_utils._ensure_admin = lambda: None
    core_utils._add_defender_exclusions = lambda: None

    token_manager._get_base_dir = lambda: str(EXTERNAL_ASSETS_ROOT)
    token_manager._get_all_base_dirs = _base_dirs
    token_manager.PROXY_FILE = str(EXTERNAL_ASSETS_ROOT / "proxy.txt")

    app_main = _load_pyc_module("apimaster_main", ROOT / "main.pyc")
    app_main.resource_path = _resource_path
    app_main._resolve_data_path = _resolve_data_path
    app_main.PROXY_FILE = str(EXTERNAL_ASSETS_ROOT / "proxy.txt")
    app_main._ensure_admin = lambda: None
    app_main._add_defender_exclusions = lambda: None

    app_main.main()


if __name__ == "__main__":
    main()
