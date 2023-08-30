from __future__ import annotations

__all__ = ["MSB"]

import abc
import logging
import re
import struct
import typing as tp
from dataclasses import dataclass, fields
from enum import Enum
from pathlib import Path

from soulstruct.base.game_file import GameFile
from soulstruct.base.game_types.map_types import MapEntity
from soulstruct.utilities.binary import *
from soulstruct.utilities.files import write_json
from soulstruct.utilities.misc import IDList
from soulstruct.utilities.text import PY_NAME_RE

from .msb_entry import MSBEntry
from .msb_entry_list import MSBEntryList
from .enums import MSBSupertype
from .events import BaseMSBEvent
from .models import BaseMSBModel
from .parts import BaseMSBPart
from .regions import BaseMSBRegion
from .utils import MSBSubtypeInfo, MSB_JSONEncoder

try:
    Self = tp.Self
except AttributeError:
    Self = "MSB"

if tp.TYPE_CHECKING:
    from .enums import BaseMSBSubtype

_LOGGER = logging.getLogger(__name__)


MAP_NAME_RE = re.compile(r"m(\d\d)_(\d\d)_.*")

# NOTE: Completely absent in DS1 and earlier.
MSB_HEADER_BYTES = struct.pack("4sII??BB", b"MSB ", 1, 16, False, False, 1, 255)


@dataclass(slots=True, kw_only=True)
class MSB(GameFile, abc.ABC):
    """Handles MSB ('MapStudio') data. Subclassed by each game.

    TODO: Update docstring.

    The MSB contains four types of data entries:

        Models: these are models that are available for map 'Part' entities such as map pieces, objects, characters,
            players, collisions, and navmeshes. Every Part included in the map will reference one of these models, and
            only models in this list will be loaded with the map.

        Events: these are 'things that happen' in the map, and are generally linked to Regions and/or Parts that have
            actual map coordinate data. There are numerous subtypes with additional data fields. Each event has an
            entity ID that may be referenced in the game events. There are no internal references to events inside the
            MSB, so they are never accessed by index and can be stored in any order.

        Regions: these are invisible points, shapes, and volumes that appear in the map. They are used to anchor events
            (e.g. spawn points, music, patrol points) and to perform location-based trigger checks in the game events
            (where they are referenced using their entity ID). Many MSB Events reference Regions by index, so their
            order needs to be carefully managed internally.

        Parts: these are actual map entities, including objects and characters. Each of them is linked to a model
            index, has a physical transform (translate, rotate, scale), and an optional entity ID. Characters and
            objects additionally have a collision index (their 'home' collision) and draw/display groups that determine
            when they are actually visible in the game. Some MSB Events reference Parts by index, so their order needs
            to be carefully managed internally.
    """
    EXT: tp.ClassVar[str] = ".msb"

    SUPERTYPE_LIST_HEADER: tp.ClassVar[tp.Type[BinaryStruct]]
    # Enum of MSB supertypes. Defaults to the one used by earlier games (models, events, regions, parts).
    MSB_SUPERTYPE_ENUM: tp.ClassVar[tp.Type[MSBSupertype]] = MSBSupertype
    # Dictionary mapping MSB supertype name enums to their base types. Expanded in later games.
    MSB_ENTRY_SUPERTYPES = {
        MSBSupertype.MODELS: BaseMSBModel,
        MSBSupertype.EVENTS: BaseMSBEvent,
        MSBSupertype.REGIONS: BaseMSBRegion,
        MSBSupertype.PARTS: BaseMSBPart,
    }
    # Maps MSB entry supertype names (e.g. 'POINT_PARAM_ST') to dicts that map subtype enum names to subtype info.
    MSB_ENTRY_SUBTYPES: tp.ClassVar[dict[MSBSupertype, dict[str, MSBSubtypeInfo]]]
    # Maps MSB entry supertype names (parts, etc.) to the relative offsets of their subtype enums.
    MSB_ENTRY_SUBTYPE_OFFSETS: tp.ClassVar[dict[MSBSupertype, int]]
    # Maps entry subtype names ("characters", "sounds", etc.) to their corresponding `BaseGameType`, if applicable.
    ENTITY_GAME_TYPES: tp.ClassVar[dict[str, MapEntity]]
    # Cached when first accessed. Maps subtype list names, e.g. 'map_pieces', to the list. Immutable.
    _SUBTYPE_LIST_NAMES: tp.ClassVar[tuple[str]] = None

    # Version info.
    HAS_HEADER: tp.ClassVar[bool]
    LONG_VARINTS: tp.ClassVar[bool]
    NAME_ENCODING: tp.ClassVar[str]

    # Subclasses define lists of entry subtypes here (`characters`, `sound_events`, `object_models`, etc.).

    @classmethod
    def from_reader(cls, reader: BinaryReader) -> Self:
        """Unpack an MSB from the given reader."""

        if cls.HAS_HEADER:
            header = reader.read(len(MSB_HEADER_BYTES))
            if header != MSB_HEADER_BYTES:
                raise AssertionError("Header of this MSB class did not match asserted header.")

        offset_fmt = "q" if cls.LONG_VARINTS else "i"

        # This will contain both supertype lists (e.g. "PARTS_PARAM_ST") and `MSBEntryList`s (e.g. "objects").
        entry_lists = {}  # type: dict[str, MSBEntryList[MSBEntry] | list[MSBEntry]]

        for supertype in cls.MSB_ENTRY_SUPERTYPES:
            supertype_list_header = cls.SUPERTYPE_LIST_HEADER.from_bytes(reader)
            entry_offset_count = supertype_list_header.pop("entry_offset_count")  # includes final offset to next list
            name_offset = supertype_list_header.pop("name_offset")

            entry_offsets = list(reader.unpack(f"{entry_offset_count}{offset_fmt}"))
            found_name = reader.unpack_string(offset=name_offset, encoding=cls.NAME_ENCODING)
            if found_name != supertype.value:
                raise ValueError(f"MSB internal list name '{found_name}' != expected name '{supertype.value}'.")
            entry_lists[supertype] = []
            # NOTE: Some games have empty supertype lists (e.g. "LAYER_PARAM_ST" in Elden Ring). This will still work.
            for entry_offset in entry_offsets[:-1]:  # exclude last offset
                reader.seek(entry_offset)
                cls._unpack_entry(reader, supertype, entry_lists)
            reader.seek(entry_offsets[-1])

        # Resolve entry indices to actual object references.
        for event in entry_lists[cls.MSB_SUPERTYPE_ENUM.EVENTS]:
            event: BaseMSBEvent
            event.indices_to_objects(entry_lists)

        for region in entry_lists[cls.MSB_SUPERTYPE_ENUM.REGIONS]:
            region: BaseMSBRegion
            region.indices_to_objects(entry_lists)

        for part in entry_lists[cls.MSB_SUPERTYPE_ENUM.PARTS]:
            part: BaseMSBPart
            part.indices_to_objects(entry_lists)

        for supertype_name in cls.MSB_ENTRY_SUPERTYPES:
            entry_lists.pop(supertype_name)  # only pass subtype lists to constructor

        # noinspection PyArgumentList
        return cls(**entry_lists)

    @classmethod
    def _unpack_entry(cls, reader: BinaryReader, supertype: MSBSupertype, entry_lists: dict[str, list[MSBEntry]]):
        subtype_int = reader["i", reader.position + cls.MSB_ENTRY_SUBTYPE_OFFSETS[supertype]]
        for _, subtype_info in cls.MSB_ENTRY_SUBTYPES[supertype].items():
            if subtype_info.subtype_enum.value == subtype_int:
                subtype_class = subtype_info.entry_class
                subtype_list_name = subtype_info.subtype_list_name
                break
        else:
            raise TypeError(f"Unknown '{supertype}' subtype enum value: {subtype_int}")
        try:
            entry = subtype_class.from_msb_reader(reader)
        except Exception as ex:
            _LOGGER.error(f"Error unpacking MSB entry of type '{subtype_class.__name__}': {ex}")
            raise
        # Put entry into appropriate supertype and subtype lists (creating if necessary).
        entry_lists[supertype].append(entry)
        if subtype_list_name not in entry_lists:
            entry_lists[subtype_list_name] = MSBEntryList(supertype=supertype, subtype_info=subtype_info)
        entry_lists[subtype_list_name].append(entry)

    @classmethod
    def resolve_supertype_name(cls, supertype_name: str) -> MSBSupertype:
        return cls.MSB_SUPERTYPE_ENUM.resolve(supertype_name)

    def get_supertype_list(self, supertype: MSBSupertype | str) -> list[MSBEntry]:
        """Construct a list of all MSB entries with the given supertype (e.g. "PARTS_PARAM_ST")."""
        supertype = self.MSB_SUPERTYPE_ENUM.resolve(supertype)
        supertype_list = []
        for subtype_list in self:
            if subtype_list.supertype == supertype:
                supertype_list.extend(subtype_list)
        return supertype_list

    def get_models(self) -> list[BaseMSBModel]:
        # noinspection PyTypeChecker
        return self.get_supertype_list(self.MSB_SUPERTYPE_ENUM.MODELS)

    def get_events(self) -> list[BaseMSBEvent]:
        # noinspection PyTypeChecker
        return self.get_supertype_list(self.MSB_SUPERTYPE_ENUM.EVENTS)

    def get_regions(self) -> list[BaseMSBRegion]:
        # noinspection PyTypeChecker
        return self.get_supertype_list(self.MSB_SUPERTYPE_ENUM.REGIONS)

    def get_parts(self) -> list[BaseMSBPart]:
        # noinspection PyTypeChecker
        return self.get_supertype_list(self.MSB_SUPERTYPE_ENUM.PARTS)

    def get_list_of_entry(self, entry: MSBEntry) -> MSBEntryList:
        """Find subtype list that contains exact instance `entry` (e.g. for an event's attached region/part)."""
        for entry_list in self:
            if entry in entry_list:
                return entry_list
        raise ValueError(f"Entry '{entry.name}' does not appear anywhere in this MSB.")

    def to_writer(self) -> BinaryWriter:
        entry_lists = {name: getattr(self, name) for name in self.get_subtype_list_names()}
        for supertype_name in self.MSB_ENTRY_SUPERTYPES:
            entry_lists[supertype_name] = self.get_supertype_list(supertype_name)

        # Check for duplicate names within supertypes (except events, where duplicates are permitted and common).
        for supertype_name in (
            self.MSB_SUPERTYPE_ENUM.MODELS, self.MSB_SUPERTYPE_ENUM.REGIONS, self.MSB_SUPERTYPE_ENUM.PARTS
        ):
            names = set()
            for entry in entry_lists[supertype_name]:
                if entry.name in names:
                    _LOGGER.warning(f"Duplicate '{supertype_name}' name in MSB: {entry.name}")
                else:
                    names.add(entry.name)

        # Get model instance counts.
        model_instance_counts = {}
        for part in entry_lists[self.MSB_SUPERTYPE_ENUM.PARTS]:
            part: BaseMSBPart
            if part.model is None:
                continue
            if part.model.name in model_instance_counts:
                model_instance_counts[part.model.name] += 1
            else:
                model_instance_counts[part.model.name] = 1

        # TODO: use writer.long_varints to communicate encoding?
        writer = BinaryWriter(byte_order=ByteOrder.LittleEndian, long_varints=self.LONG_VARINTS)
        if self.HAS_HEADER:
            writer.append(MSB_HEADER_BYTES)

        for supertype_name in self.MSB_ENTRY_SUPERTYPES:
            supertype_list = entry_lists[supertype_name]
            self.SUPERTYPE_LIST_HEADER.object_to_writer(
                self,
                writer,
                name_offset=RESERVED,
                entry_offset_count=len(supertype_list) + 1,  # includes final offset to next supertype list
            )
            for entry in supertype_list:
                writer.reserve("entry_offset", "v", obj=entry)
            writer.reserve("next_list_offset", "v", obj=supertype_list)

            writer.fill_with_position("name_offset", obj=self)
            self.pack_supertype_name(writer, supertype_name)

            for supertype_index, entry in enumerate(supertype_list):
                entry: MSBEntry
                writer.fill_with_position("entry_offset", obj=entry)
                subtype_name = self.MSB_ENTRY_SUBTYPES[supertype_name][entry.SUBTYPE_ENUM.name].subtype_list_name
                subtype_index = entry_lists[subtype_name].index(entry)
                if supertype_name == self.MSB_SUPERTYPE_ENUM.MODELS:
                    entry: BaseMSBModel
                    instance_count = model_instance_counts.get(entry.name, 0)
                    if instance_count == 0 and entry.name not in {"c0000", "c1000"}:
                        _LOGGER.warning(f"Model '{entry.name}' is not used by any parts in this MSB.")
                    try:
                        entry.to_msb_writer(writer, supertype_index, subtype_index, entry_lists, instance_count)
                    except Exception as ex:
                        _LOGGER.error(
                            f"Exception occurred while trying to write entry '{entry.name}': {ex}.\n"
                            f"  Entry: {entry}"
                        )
                        raise
                else:
                    try:
                        entry.to_msb_writer(writer, supertype_index, subtype_index, entry_lists)
                    except Exception as ex:
                        _LOGGER.error(
                            f"Exception occurred while trying to write entry '{entry.name}': {ex}.\n"
                            f"  Entry: {entry}"
                        )
                        raise

            # NOTE: "PARTS_PARAM_ST" is still the last supertype list in every known game.
            if supertype_name == self.MSB_SUPERTYPE_ENUM.PARTS:
                writer.fill("next_list_offset", 0, obj=supertype_list)  # zero offset
            else:
                writer.fill_with_position("next_list_offset", obj=supertype_list)

        return writer

    @abc.abstractmethod
    def pack_supertype_name(self, writer: BinaryWriter, supertype_name: str):
        """Differs between versions slightly."""

    def find_entry_name(
        self, name: str, supertypes: tp.Iterable[str] = (), subtypes: tp.Iterable[str] = ()
    ) -> MSBEntry:
        """Get `MSBEntry` with name `name` that is one of the given `entry_subtypes` or any type by default.

        Raises a `KeyError` if the name cannot be found, and a `ValueError` if multiple entries are found.
        """
        if subtypes:  # lower case
            entry_lists = [getattr(self, f.lower()) for f in subtypes]  # type: list[MSBEntryList]
        else:
            entry_lists = self.get_all_subtype_lists()

        if supertypes:
            supertype_names = [self.resolve_supertype_name(name) for name in supertypes]
            entry_lists = [entry_list for entry_list in entry_lists if entry_list.supertype in supertype_names]

        results = []
        for subtype_list in entry_lists:
            try:
                # This will raise a `ValueError` if the name appears more than once in a single entry type list.
                results.append(subtype_list.find_entry_name(name))
            except KeyError:
                pass  # name does not appear in this list
        if not results:
            if supertypes and subtypes:
                type_msg = f"supertype in {supertypes} and subtype in {subtypes}"
            elif supertypes:
                type_msg = f"supertype in {supertypes}"
            elif subtypes:
                type_msg = f"subtype in {subtypes}"
            else:
                type_msg = "any type"
            raise KeyError(f"Could not find an entry named '{name}' with {type_msg} in MSB.")
        if len(results) > 1:
            raise ValueError(f"Found entries of multiple types with name '{name}': {list(results)}")
        return results[0]

    def find_model_name(self, name: str | Enum, subtypes: tp.Iterable[str] = ()) -> BaseMSBModel:
        """Get `MSBModel` with name `name` that is one of the given `entry_subtypes` or any type by default.

        Raises a `KeyError` if the name cannot be found, and a `ValueError` if multiple entries are found.
        """
        if isinstance(name, Enum):
            name = name.name
        # noinspection PyTypeChecker
        return self.find_entry_name(name, supertypes=[self.MSB_SUPERTYPE_ENUM.MODELS], subtypes=subtypes)

    def find_event_name(self, name: str | Enum, subtypes: tp.Iterable[str] = ()) -> BaseMSBEvent:
        """Get `MSBEvent` with name `name` that is one of the given `entry_subtypes` or any type by default.

        Raises a `KeyError` if the name cannot be found, and a `ValueError` if multiple entries are found.
        """
        if isinstance(name, Enum):
            name = name.name
        # noinspection PyTypeChecker
        return self.find_entry_name(name, supertypes=[self.MSB_SUPERTYPE_ENUM.EVENTS], subtypes=subtypes)

    def find_region_name(self, name: str | Enum, subtypes: tp.Iterable[str] = ()) -> BaseMSBRegion:
        """Get `MSBRegion` with name `name` that is one of the given `entry_subtypes` or any type by default.

        Raises a `KeyError` if the name cannot be found, and a `ValueError` if multiple entries are found.
        """
        if isinstance(name, Enum):
            name = name.name
        # noinspection PyTypeChecker
        return self.find_entry_name(name, supertypes=[self.MSB_SUPERTYPE_ENUM.REGIONS], subtypes=subtypes)

    def find_part_name(self, name: str | Enum, subtypes: tp.Iterable[str] = ()) -> BaseMSBPart:
        """Get `MSBPart` with name `name` that is one of the given `entry_subtypes` or any type by default.

        Raises a `KeyError` if the name cannot be found, and a `ValueError` if multiple entries are found.
        """
        if isinstance(name, Enum):
            name = name.name
        # noinspection PyTypeChecker
        return self.find_entry_name(name, supertypes=[self.MSB_SUPERTYPE_ENUM.PARTS], subtypes=subtypes)

    def reattach_entry_references(self, warn_reattachments=False, backup_converter: tp.Callable[[str], str] = None):
        """Iterate over all Parts and Events, and reattach same-named references to other entries in this MSB.

        For example, if an `MSBCharacter.draw_parent` is set to a collision that is no longer in this MSB, this method
        will search for a collision with the same name and reattach that reference. If no name match is found, an error
        is raised.

        Must be called manually so you know what you're doing.
        """
        for subtype_name, entry_list in zip(("part", "event"), (self.get_parts(), self.get_events())):
            for entry in entry_list:
                for field_name in entry.MSB_ENTRY_REFERENCES:
                    field_value = getattr(entry, field_name)
                    if field_value is None:
                        if subtype_name == "part" and field_name == "model":  # cannot be None
                            raise ValueError(f"Part {entry} has no model.")
                        continue  # can be None  # TODO: but there are some fields that should almost never be None!
                    if isinstance(field_value, list):
                        for i, item in enumerate(tuple(field_value)):
                            if item is None:
                                continue
                            if not isinstance(item, MSBEntry):
                                raise ValueError(
                                    f"Index {i} of sequence field `{field_name}` of {subtype_name} '{entry.name}' "
                                    f"is not an MSBEntry: {item}"
                                )
                            try:
                                referenced_entry = self.find_entry_name(item.name)
                            except KeyError:
                                if backup_converter:
                                    try:
                                        referenced_entry = self.find_entry_name(backup_converter(item.name))
                                    except KeyError:
                                        raise KeyError(
                                            f"Could not find entry with name '{item.name}' referenced by index {i} of "
                                            f"sequence field `{field_name}` in {subtype_name} '{entry.name}'."
                                        )
                                else:
                                    raise KeyError(
                                        f"Could not find entry with name '{item.name}' referenced by index {i} of "
                                        f"sequence field `{field_name}` in {subtype_name} '{entry.name}'."
                                    )
                            if item is referenced_entry:
                                continue  # already attached
                            field_value[i] = referenced_entry  # attach to same-named entity
                        continue

                    if not isinstance(field_value, MSBEntry):
                        raise ValueError(
                            f"Field `{field_name}` of {subtype_name} '{entry.name}' is not an MSBEntry: {field_value}"
                        )

                    try:
                        referenced_entry = self.find_entry_name(field_value.name)
                    except KeyError:
                        if backup_converter:
                            try:
                                referenced_entry = self.find_entry_name(backup_converter(field_value.name))
                            except KeyError:
                                raise KeyError(
                                    f"Could not find entry with name '{field_value.name}' referenced by "
                                    f"field `{field_name}` in {subtype_name} '{entry.name}'."
                                )
                        else:
                            raise KeyError(
                                f"Could not find entry with name '{field_value.name}' referenced by "
                                f"field `{field_name}` in {subtype_name} '{entry.name}'."
                            )
                    if field_value is referenced_entry:
                        continue  # already attached
                    setattr(entry, field_name, referenced_entry)  # attach to same-named entity
                    if warn_reattachments:
                        _LOGGER.warning(
                            f"Reattached dangling reference to '{field_value.name}' in "
                            f"field `{field_name}` of {subtype_name} '{entry.name}'."
                        )

    def to_dict(self, ignore_defaults=True) -> dict[str, tp.Any]:
        """Return a dictionary form of the MSB.

        Fully serializes `MSBEntry` contents by converting inter-entry references to dictionaries.

        If `ignore_defaults=True` (default), entry fields that have the default values for that entry subclass will not
        be included in the entry's dictionary.

        NOTE: No MSB header information needs to be recorded. Just the version info.
        """
        entry_lists = self.get_all_subtype_lists()
        msb_dict = {"version": self.get_version_dict()}  # type: dict[str, dict[str, tp.Any]]
        for subtype_list in entry_lists:
            for supertype_name in self.MSB_ENTRY_SUPERTYPES:
                if subtype_list.supertype == supertype_name:
                    msb_dict.setdefault(supertype_name, {}).update(subtype_list.to_json_dict(self, ignore_defaults))
        return msb_dict

    def write_json(
        self,
        file_path: None | str | Path,
        encoding="utf-8",
        indent=4,
        ignore_defaults=True,
    ):
        """Create a dictionary from instance and write it to a JSON file.

        The file path will have the `.json` suffix added automatically if missing.
        """
        json_dict = self.to_dict(ignore_defaults=ignore_defaults)
        if file_path is None:
            if self.path is None:
                raise ValueError("You must specify `file_path` because file default `path` has not been set.")
            file_path = self.path
        file_path = Path(file_path)
        if file_path.suffix != ".json":
            file_path = file_path.with_suffix(file_path.suffix + ".json")
        write_json(file_path, json_dict, indent=indent, encoding=encoding, encoder=MSB_JSONEncoder)

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        """Load MSB from dictionary of version info and entries (sorted by supertype and nested subtype keys)."""

        if "version" not in data:
            raise ValueError("MSB dictionary is missing 'version' key.")
        if data["version"] != cls.get_version_dict():
            raise TypeError(f"Invalid MSB 'version' info in dict for this MSB class: {data['version']}")

        subtype_lists = {}
        deferred_refs = {}
        for supertype_name in cls.MSB_ENTRY_SUPERTYPES:
            if supertype_name not in data:
                # TODO: *Not* unusual for LAYERS in Elden Ring.
                # _LOGGER.warning(f"No '{supertype_name}' key found in MSB dictionary, which is unusual.")
                continue
            subtype_dict = data[supertype_name]
            for subtype_enum_name, subtype_list in subtype_dict.items():
                subtype_info = cls.MSB_ENTRY_SUBTYPES[supertype_name][subtype_enum_name]
                entries = []
                subtype_deferred = deferred_refs[subtype_info.subtype_list_name] = []
                for entry_dict in subtype_list:
                    entry, deferred = subtype_info.entry_class.from_json_dict(entry_dict)
                    if deferred:
                        subtype_deferred.append((entry, deferred))
                    entries.append(entry)
                subtype_lists[subtype_info.subtype_list_name] = MSBEntryList(
                    *entries, supertype=supertype_name, subtype_info=subtype_info
                )

        cls._resolve_deferred_json_refs(subtype_lists, deferred_refs)

        return cls(**subtype_lists)

    @classmethod
    def _resolve_deferred_json_refs(cls, subtype_lists: dict[str, MSBEntryList], deferred_refs: dict):
        """Resolve deferred entry references now that all lists are complete."""
        for subtype_list_name, deferred_list in deferred_refs.items():
            for entry, deferred_dict in deferred_list:
                for field_name, field_ref in deferred_dict.items():
                    if isinstance(field_ref, dict):
                        ref_list_name = field_ref["subtype_list_name"]
                        ref_index = field_ref["subtype_index"]
                        try:
                            ref_entry = subtype_lists[ref_list_name][ref_index]
                        except (KeyError, IndexError):
                            raise ValueError(
                                f"Entry '{entry.name}' field `{field_name}` references invalid entry: "
                                f"`{ref_list_name}[{ref_index}]`"
                            )
                        setattr(entry, field_name, ref_entry)
                    elif isinstance(field_ref, list):
                        entry_list = []
                        for ref in field_ref:
                            if ref is None:
                                entry_list.append(None)
                            else:
                                ref_list_name = ref["subtype_list_name"]
                                ref_index = ref["subtype_index"]
                                try:
                                    ref_entry = subtype_lists[ref_list_name][ref_index]
                                except (KeyError, IndexError):
                                    raise ValueError(
                                        f"Entry '{entry.name}' field `{field_name}` references invalid entry in list: "
                                        f"`{ref_list_name}[{ref_index}]`"
                                    )
                                entry_list.append(ref_entry)
                        setattr(entry, field_name, entry_list)

    @classmethod
    def get_version_dict(cls) -> dict[str, bool | str]:
        return {
            "has_header": cls.HAS_HEADER,
            "long_varints": cls.LONG_VARINTS,
            "name_encoding": cls.NAME_ENCODING,
        }

    @classmethod
    def get_subtype_list_names(cls) -> tuple[str]:
        if cls._SUBTYPE_LIST_NAMES is not None:
            return cls._SUBTYPE_LIST_NAMES
        cls._SUBTYPE_LIST_NAMES = tuple(f.name for f in fields(cls) if f.name not in {"path", "_dcx_type", "dcx_type"})
        return cls._SUBTYPE_LIST_NAMES

    def get_all_subtype_lists(self) -> list[MSBEntryList]:
        return [getattr(self, list_name) for list_name in self.get_subtype_list_names()]

    @classmethod
    def resolve_subtype_name(cls, subtype_name: str, assert_supertype_name: str = None) -> str:
        """Parse `subtype_name` (which could be an enum name or class name) to its subtype list name."""
        for supertype_name, subtype_info_list in cls.MSB_ENTRY_SUBTYPES.items():
            if assert_supertype_name is not None and supertype_name != assert_supertype_name:
                continue
            for info in subtype_info_list.values():
                if info.matches_name(subtype_name):
                    return info.subtype_list_name
        raise KeyError(f"Invalid MSB subtype name: {subtype_name}")

    def resolve_entries_list(
        self,
        entries: tp.Sequence[str | MSBEntry],
        supertypes: tp.Iterable[str] = (),
        subtypes: tp.Iterable[str] = (),
    ) -> IDList[MSBEntry]:
        """Lists of entries can include names of entries, if unique, or the actual `MSBEntry` instances."""
        if not entries:
            return IDList()
        resolved = IDList()
        for entry in entries:
            if isinstance(entry, str):
                resolved.append(self.find_entry_name(entry, supertypes, subtypes))
            elif isinstance(entry, MSBEntry):
                resolved.append(entry)
            else:
                raise TypeError(f"Invalid MSB entry specifier: {entry}. Must be a (unique) entry name or `MSBEntry`.")
        return resolved

    def get_repeated_entity_ids(self) -> dict[str, list[MSBEntry]]:
        """Scans all entries for repeated `entity_id` fields PER SUPERTYPE, not subtype.

        Repeated entity IDs in Parts appear to be mostly benign -- the first one will simply be used -- but repeated IDs
        in Regions (in DS1 at least) cause a fatal problem, as ALL entity IDs that occur after the first duplicated ID
        will simply not work. (Infamously, this is the case in vanilla m17_00_00_00, Duke's Archives.)

        Repeated IDs across different supertypes will be ignored.
        """
        repeats = {}
        for supertype_name in self.MSB_SUPERTYPE_ENUM.entity_id_supertypes():
            supertype_list = self.get_supertype_list(supertype_name)
            entity_ids = set()
            repeated_entries = []  # type: list[MSBEntry]
            for entry in supertype_list:
                entity_id = entry.get_entity_id()
                if entity_id is None or entity_id <= 0:  # some subtypes have 'null' ID zero (e.g. environment events)
                    continue
                if entity_id in entity_ids:
                    repeated_entries.append(entry)
                else:
                    entity_ids.add(entity_id)
            repeats[supertype_name] = repeated_entries
        return repeats

    def get_supertype_entity_id_dict(self, supertype_name: str) -> dict[int, MSBEntry]:
        """Get a dictionary mapping entity IDs to `MSBEntry` instances for the given supertype.

        If multiple `MSBEntry` instances are found for a given ID, a warning is logged, and only the *first* one found
        is used (which matches game engine behavior).

        Analogous to the subtype-only method in `MSBEntryList`.
        """
        supertype_list = self.get_supertype_list(supertype_name)
        entries_by_id = {}
        for entry in supertype_list:
            entity_id = entry.get_entity_id()
            if entity_id is None or entity_id <= 0:
                continue  # ignore unavailable or null ID
            if entity_id in entries_by_id:
                _LOGGER.warning(f"Found multiple entries for entity ID {entity_id}. Only using first.")
            else:
                entries_by_id[entity_id] = entry
        return entries_by_id

    def get_supertype_entity_id_name_dict(self, supertype_name: str) -> dict[int, str]:
        """As above, but values are just entry names instead of the entries themselves."""
        entries_by_id = self.get_supertype_entity_id_dict(supertype_name)
        return {entity_id: entry.name for entity_id, entry in entries_by_id.items()}

    def find_entry_by_entity_id(self, entity_id: int, allow_multiple=True) -> MSBEntry | None:
        """Search ALL entries for the given entity ID and return that `MSBEntry` (or `None` if not found).

        If multiple entries with the same (non-default) ID are found, an error will be raised unless
        `allow_multiple=True`.
        """
        if entity_id <= 0:
            raise ValueError(f"Cannot find MSB entry using default entity ID value {entity_id}.")
        results = []
        for supertype_name in (
            self.MSB_SUPERTYPE_ENUM.EVENTS, self.MSB_SUPERTYPE_ENUM.REGIONS, self.MSB_SUPERTYPE_ENUM.PARTS
        ):  # not MODELS
            supertype_list = self.get_supertype_list(supertype_name)
            results.extend([entry for entry in supertype_list if entry.get_entity_id() == entity_id])
        if not results:
            raise KeyError(f"Could not find an entry with entity ID {entity_id} in MSB.")
        elif len(results) > 1:
            if allow_multiple:
                _LOGGER.warning(
                    f"Found multiple entries with entity ID {entity_id} in MSB. This should be fixed. "
                    f"Returning first one only."
                )
            else:
                raise ValueError(f"Found multiple entries with entity ID {entity_id} in MSB. This must be fixed.")
        return results[0]

    def remove_entry(self, entry: MSBEntry):
        """Find list containing entry and remove it."""
        subtype_list = self.get_list_of_entry(entry)
        subtype_list.remove(entry)

    def clear_all(self):
        """Clear all entry subtype lists."""
        for entry_list in self.get_all_subtype_lists():
            entry_list.clear()

    def __iter__(self):
        """Iterate over all subtype lists."""
        return iter(self.get_all_subtype_lists())

    def write_enums_module(
        self,
        module_path: str | Path = None,
        area_id: int = None,
        block_id: int = None,
        # TODO: cc_id and dd_id for Elden Ring
        append_to_module: str = ""
    ):
        """Generates a '{mXX_YY}_enums.py' file with entity IDs for import into EVS scripts.

        If `append_to_module` text is given, all map enums will be appended to it.
        """
        if module_path is None:
            if self.path is None:
                raise ValueError("Cannot auto-detect MSB entities `module_path` (MSB path not known).")
            module_path = self.path.parent / f"{self.path.name.split('.')[0]}_enums.py"

        module_path.parent.mkdir(parents=True, exist_ok=True)

        auto_map_range_start = None
        if area_id is None and block_id is None:
            if self.path:
                map_name_match = MAP_NAME_RE.match(self.path.name)
                if map_name_match:
                    area_id, block_id = map(int, map_name_match.group(1, 2))
                    auto_map_range_start = area_id * 100000 + block_id * 10000
                else:
                    _LOGGER.warning(
                        f"Could not auto-detect map area and block (cannot parse from MSB path: {self.path}). "
                        "Auto-enumerator functions will be commented out; replace the {MAP_RANGE_START} string in each "
                        "one and uncomment to use."
                    )
            else:
                _LOGGER.warning(
                    "Could not auto-detect map area and block (MSB path not known). Auto-enumerator functions will be"
                    "commented out; replace the {MAP_RANGE_START} string in each one and uncomment to use."
                )
        elif area_id is not None and block_id is not None:
            # TODO: Is this still right for Elden Ring? For legacy dungeons, at least.
            auto_map_range_start = area_id * 100000 + block_id * 10000
        else:
            raise ValueError("Both `area_id` and `block_id` must be given, or neither for automatic detection.")

        trailing_digit_re = re.compile(r"(.*?)(\d+)")

        def sort_key(key_value) -> tuple[str, int]:
            """Sort trailing digits properly."""
            _, value_ = key_value
            if match := trailing_digit_re.match(value_.name):
                return match.group(1), int(match.group(2))
            return value_.name, 0

        module_path = Path(module_path)

        game_types_import = f"from soulstruct.{self.get_game().submodule_name}.game_types import *\n"
        if append_to_module:
            if game_types_import not in append_to_module:
                # Add game type start import to module. (Very rare that it wouldn't already be there.)
                first_class_def_index = append_to_module.find("\nclass")
                if first_class_def_index != -1:
                    append_to_module = append_to_module.replace("\nclass", game_types_import + "\n\nclass", 1)
                else:
                    append_to_module += game_types_import
            module_text = append_to_module.rstrip("\n") + "\n"
        else:
            module_text = game_types_import

        for subtype_name, subtype_game_type in self.ENTITY_GAME_TYPES.items():
            class_name = subtype_game_type.get_msb_entry_supertype_subtype(pluralized_subtype=True)[1]
            class_text = ""
            subtype_list = getattr(self, subtype_name)
            entity_id_dict = subtype_list.get_entity_id_dict()
            sorted_entity_id_dict = {
                k: v for k, v in sorted(entity_id_dict.items(), key=sort_key)
            }
            for entity_id, entry in sorted_entity_id_dict.items():
                # name = entry.name.replace(" ", "_")
                try:
                    name = entry.name.encode("utf-8").decode("ascii")
                except UnicodeDecodeError:
                    class_text += f"    # TODO: Non-ASCII name characters.\n    # {entry.name} = {entity_id}"
                else:
                    if not PY_NAME_RE.match(name):
                        class_text += f"    # TODO: Invalid variable name.\n    # {entry.name} = {entity_id}"
                    else:
                        class_text += f"    {name} = {entity_id}"
                if entry.description:
                    class_text += f"  # {entry.description}"
                class_text += "\n"
            if class_text:
                class_def = f"\n\nclass {class_name}({subtype_game_type.__name__}):\n"
                class_def += f"    \"\"\"`{subtype_game_type.__name__}` entity IDs for MSB and EVS use.\"\"\"\n\n"
                auto_lines = [
                    "    # noinspection PyMethodParameters",
                    "    def _generate_next_value_(name, _, count, __):",
                    f"        return {subtype_game_type.__name__}.auto_generate(ID_RANGES, count, {{MAP_RANGE_START}})",
                ]
                if auto_map_range_start is None:
                    auto_lines = ["    # " + line[4:] for line in auto_lines]
                else:
                    auto_lines[-1] = auto_lines[-1].format(MAP_RANGE_START=auto_map_range_start)
                class_def += "\n".join(auto_lines) + "\n\n"
                class_text = class_def + class_text
                module_text += class_text

        with module_path.open("w", encoding="utf-8") as f:
            f.write(module_text)

    def get_or_create_model(
        self,
        model_subtype_name: str,
        name: str,
        sib_path="",
        map_stem="",
        replace_existing=False,
    ) -> BaseMSBModel:
        """Get or create a model of the given subtype, with the given name and SIB path.

        Specify `replace_existing` if you want to replace an existing model with the same name, e.g. with a new SIB.
        """
        for subtype_name, part_info in self.MSB_ENTRY_SUBTYPES[self.MSB_SUPERTYPE_ENUM.PARTS].items():
            # Redirect part subtype names to their corresponding model subtype names.
            if part_info.matches_name(model_subtype_name):
                subtype_list_name = f"{subtype_name}Model"
                break
        else:
            subtype_list_name = self.resolve_subtype_name(model_subtype_name, self.MSB_SUPERTYPE_ENUM.MODELS)
        model_list = self[subtype_list_name]
        try:
            model = model_list.find_entry_name(name)  # model with this name already exists
            if not replace_existing:
                return model
        except KeyError:
            model = self[subtype_list_name].new(name=name, sib_path=sib_path)  # type: BaseMSBModel
            if not model.sib_path:
                if map_stem:  # prevents empty `map_stem` from being formatted
                    model.set_auto_sib_path(map_stem=map_stem)
                else:
                    model.set_auto_sib_path()
        else:
            # Modify existing model.
            model.sib_path = sib_path
            if not model.sib_path:
                if map_stem:  # prevents empty `map_stem` from being formatted
                    model.set_auto_sib_path(map_stem=map_stem)
                else:
                    model.set_auto_sib_path()
        return model

    def has_c0000_model(self) -> bool:
        """Common check for character/player model c0000, which should be in every MSB (in every game)."""
        character_models = getattr(self, "character_models")  # type: MSBEntryList
        try:
            character_models.find_entry_name("c0000")
        except KeyError:
            player_models = getattr(self, "player_models")
            try:
                player_models.find_entry_name("c0000")
            except KeyError:
                return False
        return True

    @classmethod
    def get_display_type_dict(cls) -> dict[str, tuple[BaseMSBSubtype]]:
        """Return a nested dictionary mapping MSB type names (in typical display order) to tuples of subtype enums."""
        display_dict = {}  # type: dict[str, tuple[BaseMSBSubtype]]
        for supertype_name, subtypes_info in cls.MSB_ENTRY_SUBTYPES.items():
            display_dict[supertype_name] = tuple(info.subtype_enum for info in subtypes_info.values())
        return {
            "Parts": display_dict[cls.MSB_SUPERTYPE_ENUM.PARTS],
            "Regions": display_dict[cls.MSB_SUPERTYPE_ENUM.REGIONS],
            "Events": display_dict[cls.MSB_SUPERTYPE_ENUM.EVENTS],
            "Models": display_dict[cls.MSB_SUPERTYPE_ENUM.MODELS],
        }

    def __getitem__(self, subtype_name: str) -> MSBEntryList:
        """Retrieve entry subtype list by name, e.g. "characters", or enum name, e.g. "Character"."""
        subtype_list_name = self.resolve_subtype_name(subtype_name)
        return getattr(self, subtype_list_name)

    def get_models_of_part_subtype(self, part_subtype_name: str) -> MSBEntryList:
        """Retrieve all models that are used by the given part subtype."""
        model_subtype_list_name = self.resolve_subtype_name(part_subtype_name + "Model", self.MSB_SUPERTYPE_ENUM.MODELS)
        return getattr(self, model_subtype_list_name)

    def get_map_stem(self) -> str:
        """Get the map stem (e.g. 'm10_01_00_00') from the MSB path, if possible."""
        if self.path is None:
            raise ValueError("Cannot get map stem from MSB path because it is not known.")
        if map_name_match := MAP_NAME_RE.match(self.path.name):
            return map_name_match.group(0)
        raise ValueError(f"Could not parse map stem from MSB path name: {self.path}")
