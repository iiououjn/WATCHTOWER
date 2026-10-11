from __future__ import annotations

import re
import subprocess

_FREE = re.compile(r"free percentage:\s*(\d+)%")


def free_ram_pct(run=subprocess.run) -> int | None:
    """System-wide free memory % from macOS `memory_pressure`; None if it cannot be read."""
    try:
        out = run(["memory_pressure"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = _FREE.search(out or "")
    return int(match.group(1)) if match else None
