from pathlib import Path

_pkg_root = Path(__file__).resolve().parent.parent / "PYZ.pyz_extracted" / "services"
if _pkg_root.is_dir():
    __path__.append(str(_pkg_root))
