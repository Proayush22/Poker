"""Application entry point for the poker bot."""

import os
import site
import sys


def _enable_macos_user_packages():
    """Load packages installed by ``python3 -m pip --user`` when needed."""
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    user_packages = os.path.expanduser(
        f"~/Library/Python/{version}/lib/python/site-packages"
    )
    if os.path.isdir(user_packages):
        site.addsitedir(user_packages)


_enable_macos_user_packages()
os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

from ui import run_app


if __name__ == "__main__":
    run_app()
