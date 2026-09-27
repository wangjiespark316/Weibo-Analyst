# FastAPI 微博数据服务

# --- compat: sibling modules importable in both package(uvicorn/scheduler) and script mode ---
import os as _os, sys as _sys
_pkg_dir = _os.path.dirname(_os.path.abspath(__file__))
if _pkg_dir not in _sys.path:
    _sys.path.append(_pkg_dir)
