from __future__ import annotations

__all__ = ["convert_events", "compare_events"]

import logging
import typing as tp
from pathlib import Path

from .emevd.exceptions import EMEVDError

if tp.TYPE_CHECKING:
    from soulstruct.darksouls1ptde.game_types.map_types import Map
    from .emevd import EMEVD

_LOGGER = logging.getLogger(__name__)

EVENT_EXTENSIONS = {
    "evs": {".evs", ".evs.py", ".py", ".emevd.py"},
    "emevd": {".emevd"},
    "emevd.dcx": {".emevd.dcx"},
    "numeric": {".numeric", ".txt", ".numeric.txt"},
}
ALL_EXTENSIONS = (
    EVENT_EXTENSIONS["evs"] | EVENT_EXTENSIONS["emevd"] | EVENT_EXTENSIONS["emevd.dcx"] | EVENT_EXTENSIONS["numeric"]
)


def convert_events(
    output_type: str,
    output_directory: str | Path,
    input_directory: str | Path,
    maps: tp.Iterable[Map],
    emevd_class: tp.Type[EMEVD],
    input_type: tp.Optional[str] = None,
    check_hash=False,
    merge_emevd_sources: tp.Sequence[str | Path] = (),
):
    """Convert all events from one format to another.

    The possible formats are 'evs' (or 'py'), 'emevd', 'emevd.dcx', and 'numeric' (or 'txt'). By default, the input
    type is auto-detected from the name of each EMEVD file with the appropriate map formatting (e.g.
    'm10_00_00_00.emevd.py', 'm10_01_00_00.numeric.txt') in the input directory (which defaults to the packaged vanilla
    'evs.py' scripts).

    A subset of EMEVD map constants to convert can be passed to `maps`, or it can be left to default to looking for all
    EMEVD files used in this game (in which case an error will be raised if any are not found).

    If `check_hash=True`, the file will not be written if a file with the same hash already exists.

    If any `merge_emevd_sources` are given, sources with a shortest stem (i.e. ignoring ALL file extensions) that
    matches one of the map's EMEVD file stems will be merged into that `EMEVD` before conversion.
    """
    output_ext = "." + output_type.lower().lstrip(".")
    output_type = None
    for ext_type, exts in EVENT_EXTENSIONS.items():
        if output_ext in exts:
            output_type = ext_type
            break
    if output_type is None:
        raise ValueError(f"Invalid EMEVD output extension: {repr(output_ext)}.")
    if output_type in {"evs", "numeric"} and check_hash:
        raise ValueError(f"Cannot use `check_hash=True` for EMEVD output type '{output_type}'.")

    output_directory = Path(output_directory)
    input_ext = "." + input_type.lower().lstrip(".") if input_type is not None else None
    input_directory = Path(input_directory)
    emevd_source_paths = {m.emevd_file_stem: None for m in maps}
    merge_emevd_sources = [Path(merge_source) for merge_source in merge_emevd_sources]
    for available in input_directory.glob("*"):
        parts = available.name.split(".")
        name, ext = parts[0], "." + ".".join(parts[1:])
        if name in emevd_source_paths and (ext == input_ext or (input_ext is None and ext in ALL_EXTENSIONS)):
            if emevd_source_paths[name] is not None:
                raise FileExistsError(f"Found multiple files named {repr(name)} with different extensions.")
            emevd_source_paths[name] = available
    missing = [name for name, source in emevd_source_paths.items() if source is None]
    if missing:
        raise FileNotFoundError(f"Could not find EMEVD sources for: {missing}.")

    for name, source_path in emevd_source_paths.items():
        output_path = output_directory / (name + output_ext)
        name_stem = name.split(".")[0]
        try:
            # NOTE: EMEVD default `DCX_TYPE` applied automatically for EVS/numeric sources.
            if input_type == "evs":
                emevd = emevd_class.from_evs_path(source_path, script_directory=input_directory)
            elif input_type == "numeric":
                emevd = emevd_class.from_numeric_path(source_path, map_name=name_stem)
            else:
                emevd = emevd_class.from_path(source_path)
        except Exception as ex:
            raise EMEVDError(f"Encountered an error while attempting to load {name + output_ext}:\n  {str(ex)}")

        for merge_source in tuple(merge_emevd_sources):
            if merge_source.stem.startswith(name_stem):
                merge_emevd, source_type = emevd_class.from_auto_detect_source_type(merge_source)
                if source_type != "evs":
                    dump_name = "__" + merge_source.name.split(".")[0] + ".evs.py"
                    _LOGGER.info(f"EVS version of merge source file written for inspection: {dump_name}")
                    merge_emevd.write_evs(merge_source.with_name(dump_name))
                emevd = emevd.merge(merge_emevd)
                merge_emevd_sources.remove(merge_source)
                _LOGGER.info(f"Merged '{merge_source.name}' into {name} EMEVD.")
        try:
            if output_type == "evs":
                emevd.write_evs(output_path)
            elif output_type == "emevd":
                emevd.write(output_path, check_hash=check_hash)
            elif output_type == "emevd.dcx":
                emevd.write(output_path, check_hash=check_hash)
            elif output_type == "numeric":
                emevd.write_numeric(output_path)
        except Exception as ex:
            raise EMEVDError(f"Encountered an error while attempting to write {name + output_ext}: {str(ex)}")
    if merge_emevd_sources:
        _LOGGER.warning(f"Unused `merge_emevd_sources` after EMEVD conversion: {merge_emevd_sources}")


def compare_events(source_1, source_2, emevd_class: tp.Type[EMEVD], use_evs=True):
    """Converts both `EMEVD` sources to raw, decompiled EVS (if `use_evs=True`) or numeric form.

    Note that if a source is already an EVS script, it will still be compiled and then decompiled before comparison, so
    only genuine functional changes (or maybe semi-functional ones, like exact condition registers) will be caught here.

    Prints only the first line that differs before returning (as subsequent lines may just be offset and this isn't a
    fancy diff tool).

    TODO: dataclass equality comparison should be possible now...?
    """
    emevd_1 = emevd_class.from_auto_detect_source_type(source_1)[0]
    emevd_2 = emevd_class.from_auto_detect_source_type(source_2)[0]

    if use_evs:
        string_1 = emevd_1.to_evs()
        string_2 = emevd_2.to_evs()
    else:
        string_1 = emevd_1.to_numeric()
        string_2 = emevd_2.to_numeric()

    for i, (line_1, line_2) in enumerate(zip(string_1.split("\n"), string_2.split("\n"))):
        if line_1 != line_2:
            print(
                f"Sources disagree on (at earliest) line {i + 1}.\n"
                f"  Source 1: {line_1}\n"
                f"  Source 2: {line_2}"
            )
            return

    if use_evs:
        print("EMEVD sources have identical EVS representations.")
    else:
        print("EMEVD sources have identical 'numeric'-format representations.")
