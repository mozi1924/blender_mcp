# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Runtime tool handlers.  Importing this module registers every tool."""

from . import schemas  # noqa: F401
from . import set_property  # noqa: F401
from . import inspect  # noqa: F401
from . import capture  # noqa: F401
from . import modifier  # noqa: F401
from . import nodes  # noqa: F401
from . import script  # noqa: F401
from . import describe  # noqa: F401
from . import operator  # noqa: F401
from . import hierarchy  # noqa: F401

__all__ = [
    "schemas",
    "set_property",
    "inspect",
    "capture",
    "modifier",
    "nodes",
    "script",
    "describe",
    "operator",
    "hierarchy",
]
