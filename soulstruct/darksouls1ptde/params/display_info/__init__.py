"""Imports all names from all param categories (loosely sorted into scripts here)."""

from __future__ import annotations

import typing as tp

from .ai import *
from .attacks import *
from .behaviors import *
from .bullets import *
from .characters import *
from .effects import *
from .items import *
from .lighting import *
from .misc import *
from .objects import *
from .shops import *
from .spells import *

if tp.TYPE_CHECKING:
    from soulstruct.base.params.utils import FieldDisplayInfo


def get_param_info(param_type: str) -> dict:
    try:
        return globals()[param_type]
    except KeyError:
        raise KeyError(f"Could not find Param info for {param_type}.")


def get_param_info_field(param_type: str, field_name: str) -> FieldDisplayInfo:
    param_info = get_param_info(param_type)
    field_hits = [field for field in param_info["fields"] if field.name == field_name]
    if not field_hits:
        raise ValueError(f"Could not find field {field_name} in param {param_type}.")
    return field_hits[0]
