"""Read the Artifactum client's own settings, so the plugin needs no setup of its own.

`atfm init` saves the API token and server in ~/.artifactum/config.toml. The token can also come
from the ATFM_API_KEY environment variable (for CI, or keys kept in a secrets manager). Standard
library only, and Python 3.10+, the oldest the client supports, since this runs before anything is installed.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_SERVER = "https://atfm.io"


def config_path() -> Path:
    return Path(os.environ.get("ATFM_CONFIG", Path.home() / ".artifactum" / "config.toml")).expanduser()


def _read_toml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib  # Python 3.11+

        data = tomllib.loads(text)
        return data.get("default", data)
    except ImportError:
        # Older Pythons: the config is flat key = "value" lines, which a regex reads well enough
        return dict(re.findall(r'^\s*(\w+)\s*=\s*"([^"]*)"', text, re.M))


def load() -> dict:
    """{"token": str, "server": str, "configured": bool} from the environment and the config file."""
    section: dict = {}
    path = config_path()
    if path.exists():
        try:
            section = _read_toml(path)
        except Exception:  # an unreadable config is the same as none
            section = {}
    token = os.environ.get("ATFM_API_KEY") or str(section.get("api_token") or "")
    server = os.environ.get("ATFM_SERVER_URL") or str(section.get("server_url") or DEFAULT_SERVER)
    return {"token": token, "server": server.rstrip("/"), "configured": path.exists() or bool(token)}


def same_origin(a: str, b: str) -> bool:
    """Whether two URLs share scheme, host and port: a token is only ever sent to its own server."""
    x, y = urlsplit(a), urlsplit(b)
    return (x.scheme, x.hostname, x.port) == (y.scheme, y.hostname, y.port)
