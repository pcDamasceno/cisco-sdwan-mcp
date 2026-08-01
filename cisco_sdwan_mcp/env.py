"""
Load the project's ``.env`` file into the process environment.

Container runtimes inject the SDWAN_* variables directly (compose ``env_file``,
``docker run --env-file``, Kubernetes secrets), so anything already present in
the environment always wins. The file is a convenience for running the server
straight from a checkout — ``python -m cisco_sdwan_mcp.server`` — where nothing else would
read it.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

#: Repository root: ``<root>/cisco_sdwan_mcp/env.py`` → ``<root>``.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: Path actually loaded, or ``None`` when no file was found. Read by the server
#: at startup so the log says where the configuration came from.
loaded_env_file: Path | None = None


def load_env_file() -> Path | None:
    """Read ``.env`` into :data:`os.environ` without overriding existing values.

    ``SDWAN_ENV_FILE`` points at a different file — useful when one checkout
    talks to several controllers.

    Returns:
        The file that was loaded, or ``None`` when there is none. A missing
        file is not an error: the variables may come from the environment, and
        a missing controller is reported on the first tool call anyway.
    """
    global loaded_env_file

    override = os.getenv("SDWAN_ENV_FILE", "").strip()
    path = Path(override).expanduser() if override else PROJECT_ROOT / ".env"
    if not path.is_file():
        return None

    load_dotenv(path, override=False)
    loaded_env_file = path
    return path
