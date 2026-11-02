# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Runtime tool handlers.  Importing this module registers every tool."""

from . import schemas  # noqa: F401
from . import inspect  # noqa: F401
from . import capture  # noqa: F401
from . import transform  # noqa: F401
from . import modifier  # noqa: F401
from . import material  # noqa: F401
from . import scene_setup  # noqa: F401
from . import nodes  # noqa: F401
from . import script  # noqa: F401
from . import undo  # noqa: F401
from . import describe  # noqa: F401
from . import operator  # noqa: F401
from . import primitive  # noqa: F401

__all__ = [
    "schemas",
    "inspect",
    "capture",
    "transform",
    "modifier",
    "material",
    "scene_setup",
    "nodes",
    "script",
    "undo",
    "describe",
    "operator",
    "primitive",
]
