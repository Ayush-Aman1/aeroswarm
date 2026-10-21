"""macOS workaround for pystencils 2.0's CPU JIT.

pystencils links every generated extension module against libpython's dylib on Apple Clang. With
statically-linked interpreters (uv / python-build-standalone, some conda builds) that loads a *second*
copy of the interpreter and the module segfaults on import. Extension modules must instead resolve the
Python symbols from the running process: `-undefined dynamic_lookup`. No-op on Linux/Windows.
"""
from __future__ import annotations

import sys

_done = False


def apply() -> None:
    global _done
    if _done or sys.platform != "darwin":
        return
    from pystencils.jit.cpu import compiler_info as ci

    def linker_flags(self):
        flags = ["-shared", "-undefined", "dynamic_lookup"]
        if getattr(self, "openmp", False):
            from pathlib import Path
            for lib in ("/opt/local/lib/libomp/libomp.dylib", "/usr/local/lib/libomp.dylib", "/opt/homebrew/lib/libomp.dylib"):
                if Path(lib).exists():
                    flags.append(lib)
                    break
        return flags

    ci.AppleClangInfo.linker_flags = linker_flags
    _done = True
