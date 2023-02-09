from __future__ import annotations

__all__ = ["GameParamBND", "param_property"]

import abc
import logging
import typing as tp
from dataclasses import dataclass, field
from pathlib import Path

from soulstruct.containers import Binder, BinderEntry
from soulstruct.base.game_types import BaseGameParam
from soulstruct.utilities.files import read_json, write_json
from soulstruct.utilities.misc import BiDict

try:
    Self = tp.Self
except AttributeError:
    Self = "GameParamBND"

if tp.TYPE_CHECKING:
    from .param import Param
    from .paramdef import ParamDefBND

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class GameParamBND(Binder, abc.ABC):

    EXT: tp.ClassVar[str] = ".parambnd"
    PARAM_CLASS: tp.ClassVar[tp.Type[Param]]

    # Maps internal param names (some game-specific) to more friendly Soulstruct names. Two-way dictionary.
    # Values should match the names of getter properties on game subclass.
    PARAM_NICKNAMES: tp.ClassVar[BiDict[str, str]] = {}
    PARAM_TYPES: tp.ClassVar[dict[str, BaseGameParam]] = {}

    params: dict[str, Param] = field(default_factory=dict)
    _reload_warning_given: bool = field(init=False)

    def __post_init__(self):
        self._reload_warning_given = False
        if not self.params and self.entries:
            return

        # Load from binary Binder source.
        for entry in self.entries:
            if not entry.name.endswith(".param"):
                _LOGGER.warning(f"Ignoring unknown entry '{entry.name}' in `GameParamBND` binder.")
                continue
            try:
                self.params[entry.stem] = entry.to_game_file(self.PARAM_CLASS)  # rows not unpacked yet
            except Exception as ex:
                _LOGGER.error(f"Could not load `Param` from GameParamBND entry '{entry.name}'. Error: {ex}")
                raise

    def unpack_all_param_rows(self, paramdefbnd: ParamDefBND = None):
        """Unpack all row data of all `Param` entries with `paramdefbnd` (defaults to bundled file)."""
        if paramdefbnd is None:
            paramdefbnd = self.PARAM_CLASS.GET_BUNDLED_PARAMDEF()
        for param in self.params.values():
            param.unpack_rows(paramdefbnd)

    def regenerate_binder_entries(self):
        """Regenerate Binder entries from `params` dictionary."""

        # Remove BND talk entries that aren't still present in this `GameParamBND` instance.
        current_entry_names = [f"{param_stem}.param" for param_stem in self.params]
        for entry_name in [entry.name for entry in self.entries]:
            if entry_name not in current_entry_names:
                self.remove_entry_name(entry_name)

        for param_name, param in zip(current_entry_names, self.params.values(), strict=True):
            entry_path = self.get_default_entry_path(param_name)
            if entry_path in self.entries_by_path:
                # Just update data.
                self.entries_by_path[entry_path].set_from_game_file(param)
            else:
                # Add new entry.
                # TODO: Does GameParamBND entry ID matter? Seems to just go from 0 to whatever.
                new_id = self.get_first_new_entry_id_in_range(0, 1000000)
                new_entry = BinderEntry(data=bytes(param), entry_id=new_id, path=entry_path)
                self.add_entry(new_entry)
                _LOGGER.debug(f"New Param entry added to GameParamBND (ID {new_id}): {param_name}")

    def write(self, file_path: None | str | Path = None, make_dirs=True, check_hash=False, **pack_kwargs):
        """Write the `GameParamBND` file after updating the binary BND entries from the loaded `Param` instances.

        See `GameFile.write()` for more.
        """
        self.regenerate_binder_entries()
        super().write(file_path, make_dirs=make_dirs, check_hash=check_hash, **pack_kwargs)
        _LOGGER.info("GameParamBND written successfully.")
        if not self._reload_warning_given:
            _LOGGER.info("Remember to reload your game to see changes.")
            self._reload_warning_given = True

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        if "params" not in data:
            raise KeyError("Field `params` not specified in `GameParamBND` dict.")

        binder_kwargs = cls.process_manifest_header(data) | {"params": {}}
        for param_stem, param_dict in data["params"].items():
            param = cls.PARAM_CLASS.from_dict(param_dict)
            binder_kwargs["params"][param_stem] = param

        gameparambnd = super().from_dict(**binder_kwargs)
        # gameparambnd.regenerate_binder_entries()  # TODO: no need to create entries until needed, right?
        return gameparambnd

    def to_dict(self, ignore_pads=True, ignore_defaults=True) -> dict[str, tp.Any]:
        """Convert entire `GameParamBND` to a single dictionary with both the standard `Binder` manifest and all Param
        data (as dictionaries).

        Generally NOT preferable to `write_json_directory()`.
        """
        data = self.get_manifest_header()
        data["params"] = {}
        for param_stem, param in self.params.items():
            param_dict = param.to_dict(ignore_pads=ignore_pads, ignore_defaults=ignore_defaults)
            data["params"]["param_stem"] = param_dict
        return data

    @classmethod
    def from_json_directory(cls, directory: Path | str) -> Self:
        """Load individual Param JSON files from an unpacked Binder folder (e.g. produced by `write_json_directory()`).

        The stems of the Param JSON files to be loaded from the folder are recorded in the `entries` key of the
        `GameParamBND_manifest.json` file.

        Functionally very similar to `from_dict()`, but avoids the need for one gigantic JSON file for all Params.
        """
        directory = Path(directory)
        manifest_path = directory / "GameParamBND_manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Could not find GameParamBND manifest file '{manifest_path}'.")

        manifest = read_json(manifest_path)
        if "entries" not in manifest:
            raise ValueError(f"`entries` key not in `GameParamBND` JSON manifest: {manifest_path}")

        manifest["params"] = {}
        for json_stem in manifest.pop("entries"):
            param_stem = cls.PARAM_NICKNAMES[json_stem]
            manifest["params"][param_stem] = Param.from_json(f"{json_stem}.json")

        gameparambnd = cls.from_dict(manifest)
        gameparambnd.path = directory  # TODO: auto-detect better default path, e.g. for binary?
        return gameparambnd

    def write_json_directory(self, directory: Path | str, ignore_pads=True, ignore_defaults=True):
        """Write a folder containing a `GameParamBND_manifest.json` file with standard `Binder` header information and
        a list of Param JSON file stems to load from the same folder.

        The resulting folder can be loaded with `load_json_directory(directory)`.
        """
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        manifest = self.get_manifest_header()
        manifest.pop("use_id_prefix")
        manifest["entries"] = []

        for param_stem, param in self.params.items():
            json_stem = self.PARAM_NICKNAMES.get(param_stem, param_stem if param.nickname is None else param.nickname)
            param.write_json(directory / f"{json_stem}.json", ignore_pads=ignore_pads, ignore_defaults=ignore_defaults)
            manifest["entries"].append(json_stem)

        write_json(directory / "GameParamBND_manifest.json", manifest)

    def get_param(self, param_name: str) -> Param:
        param_name = param_name.removesuffix(".param")
        if param_name in self.params:  # easy case
            return self.params[param_name]
        if param_name in self.PARAM_NICKNAMES.values():  # values are Soulstruct nicknames
            return self.params[self.PARAM_NICKNAMES[param_name]]
        raise KeyError(f"Cannot find `Param` named '{param_name}'.")

    # TODO: Inherit from some abstract `ProjectData` class that provides this interface.
    def get_range(self, param_name: str, start: int, count: int):
        """Get a list of (id, entry) pairs from a certain range inside ID-sorted param dictionary."""
        return self.get_param(param_name).get_range(start, count)


def param_property(param_nickname: str):
    """Assists in assigning properties to `Param` nickname attribtues, e.g.:
        `ActionButtons = param_property("ActionButtons")`

    Nicknames will be looked up in `GameParamBND.PARAM_NICKNAMES` two-way dictionary.
    """
    return property(lambda self: self.params.PARAM_NICKNAMES[param_nickname])
