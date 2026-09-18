# /app/report/__init__.py
"""
Report generation package.

Modules are split by concern from the original monolithic report_generator.py.
All public symbols are re-exported here for backward compatibility:
    ``import report_generator`` still works via the shim in the project root.
"""

from .c_parsing import (
    _extract_c_definitions,
    _extract_c_function_bodies,
    _extract_c_global_candidates,
    _extract_c_macro_defs,
    _extract_c_macros,
    _extract_c_prototypes,
    _extract_simple_call_names,
    _strip_c_comments,
)
from .constants import (
    DEFAULT_TYPE_RANGES,
    GLOBALS_FORMAT_ORDER,
    GLOBALS_FORMAT_SEP,
    GLOBALS_FORMAT_WITH_LABELS,
    LOGIC_MAX_CHILDREN_DEFAULT,
    LOGIC_MAX_DEPTH_DEFAULT,
    LOGIC_MAX_GRANDCHILDREN_DEFAULT,
    UDS_PLACEHOLDERS,
    UDS_RULES,
)

__all__ = [
    "UDS_RULES",
    "UDS_PLACEHOLDERS",
    "GLOBALS_FORMAT_ORDER",
    "GLOBALS_FORMAT_SEP",
    "GLOBALS_FORMAT_WITH_LABELS",
    "LOGIC_MAX_DEPTH_DEFAULT",
    "LOGIC_MAX_CHILDREN_DEFAULT",
    "LOGIC_MAX_GRANDCHILDREN_DEFAULT",
    "DEFAULT_TYPE_RANGES",
]
