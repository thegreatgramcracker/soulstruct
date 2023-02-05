from __future__ import annotations

__all__ = ["TPFTexture", "TPF", "batch_get_tpf_texture_png_data"]

import abc
import logging
import multiprocessing
import json
import re
import tempfile
import typing as tp
import zlib
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

from soulstruct.base.base_binary_file import BaseBinaryFile
from soulstruct.base.textures.dds import DDS, DDSCAPS2, texconv, convert_dds_file
from soulstruct.utilities.binary import *

from .dcx import decompress


if tp.TYPE_CHECKING:
    from .entry import BinderEntry

_LOGGER = logging.getLogger(__name__)


class TPFPlatform(IntEnum):
    PC = 0
    Xbox360 = 1
    PS3 = 2
    PS4 = 4
    XboxOne = 5

    def get_byte_order(self):
        if self in {TPFPlatform.Xbox360, TPFPlatform.PS3}:
            return ByteOrder.BigEndian
        return ByteOrder.LittleEndian


class TextureType(IntEnum):
    Texture = 0  # one 2D texture
    Cubemap = 1  # six 2D textures
    Volume = 2  # one 3D texture


@dataclass(slots=True)
class TextureHeader:
    """Extra metadata for headerless textures used in console versions."""
    width: int
    height: int
    texture_count: int = 0
    unk1: int = 0  # unknown, PS3 only
    unk2: int = 0  # unknown, 0x0 or 0xAAE4 in DeS, 0xD in DS3 (console)
    dxgi_format: int = 0  # Microsoft DXGI_FORMAT


@dataclass(slots=True)
class TextureFloatStruct(NewBinaryStruct):
    """Unknown optional data for some textures."""
    unk0: int
    size: int = field(**BinaryAutoCompute(lambda self: 4 * len(self.values)))
    values: list[float] = field(**Binary(length=FieldValue("size", lambda size: size // 4)))


@dataclass(slots=True)
class TPFTextureStruct(NewBinaryStruct, abc.ABC):
    data_offset: uint
    data_size: int
    format: byte
    texture_type: TextureType = field(**Binary(byte))
    mipmap_count: byte
    texture_flags: byte = field(**Binary(asserted=[0, 1, 2, 3]))


@dataclass(slots=True)
class TPFTexture:

    name: str = ""
    format: int = 1
    texture_type: TextureType = TextureType.Texture
    mipmap_count: int = 0
    texture_flags: int = 0  # {2, 3} -> DCX-compressed; unknown otherwise
    data: bytes = b""
    header: TextureHeader | None = None
    float_struct: TextureFloatStruct | None = None

    @classmethod
    def from_tpf_reader(
        cls,
        reader: BinaryReader,
        platform: TPFPlatform,
        tpf_flags: int,
        encoding: str,
    ):
        texture_struct = TPFTextureStruct.from_bytes(reader)

        if platform != TPFPlatform.PC:
            width = reader.unpack_value("h")
            height = reader.unpack_value("h")
            header = TextureHeader(width, height)
            if platform == TPFPlatform.Xbox360:
                reader.assert_pad(4)
            elif platform == TPFPlatform.PS3:
                header.unk1 = reader.unpack_value("i")
                if tpf_flags != 0:
                    header.unk2 = reader.unpack_value("i")
                    if header.unk2 not in {0, 0x68E0, 0xAAE4}:
                        raise ValueError(
                            f"`TextureHeader.unk2` was {header.unk2}, but expected 0, 0x68E0, or 0xAAE4."
                        )
            elif platform in {TPFPlatform.PS4, TPFPlatform.XboxOne}:
                header.texture_count = reader.unpack_value("i")
                if header.texture_count not in {1, 6}:
                    f"`TextureHeader.texture_count` was {header.texture_count}, but expected 1 or 6."
                header.unk2 = reader.unpack_value("i")
                if header.unk2 != 0xD:
                    f"`TextureHeader.unk2` was {header.unk2}, but expected 0xD."
            # `dxgi_format` unpacked below.
        else:
            header = None

        name_offset = reader.unpack_value("I")
        has_float_struct = reader.unpack_value("i") == 1
        if platform in {TPFPlatform.PS4, TPFPlatform.XboxOne}:
            header.dxgi_format = reader.unpack_value("i")
        float_struct = TextureFloatStruct.from_bytes(reader) if has_float_struct else None

        with reader.temp_offset(texture_struct.pop("data_offset")):
            data = reader.read(texture_struct.pop("data_size"))
        if texture_struct.texture_flags in {2, 3}:
            # Data is DCX-compressed.
            # TODO: should enforce DCX type as 'DCP_EDGE'?
            data = decompress(data)

        name = reader.unpack_string(offset=name_offset, encoding=encoding)

        texture = texture_struct.to_object(
            cls,
            name=name,
            data=data,
            header=header,
            float_struct=float_struct,
        )

        return texture

    def to_tpf_writer(self, writer: BinaryWriter, platform: TPFPlatform, tpf_flags: int):
        if platform == TPFPlatform.PC:
            dds = self.get_dds()
            if dds.header.caps_2 & DDSCAPS2.CUBEMAP:
                texture_type = TextureType.Cubemap
            elif dds.header.caps_2 & DDSCAPS2.VOLUME:
                texture_type = TextureType.Volume
            else:
                texture_type = TextureType.Texture
            mipmap_count = dds.header.mipmap_count
        else:
            texture_type = self.texture_type
            mipmap_count = self.mipmap_count

        TPFTextureStruct.object_to_writer(
            self,
            writer,
            file_offset=RESERVED,
            file_size=RESERVED,
            texture_type=texture_type,
            mipmap_count=mipmap_count,
        )

        if platform != TPFPlatform.PC:
            writer.pack("h", self.header.width)
            writer.pack("h", self.header.height)
            if platform == TPFPlatform.Xbox360:
                writer.pad(4)
            elif platform == TPFPlatform.PS3:
                writer.pack("i", self.header.unk1)
                if tpf_flags != 0:
                    writer.pack("i", self.header.unk2)
            elif platform in {TPFPlatform.PS4, TPFPlatform.XboxOne}:
                writer.pack("i", self.header.texture_count)
                writer.pack("i", self.header.unk2)

        writer.reserve("name_offset", "I", obj=self)
        writer.pack("i", 0 if self.float_struct is None else 1)

        if platform in {TPFPlatform.PS4, TPFPlatform.XboxOne}:
            writer.pack("i", self.header.dxgi_format)

        if self.float_struct:
            self.float_struct.to_writer(writer)

    def pack_name(self, writer: BinaryWriter, encoding_type: int):
        writer.fill_with_position("name_offset", obj=self)
        if encoding_type == 1:  # UTF-16
            name = self.name.encode(encoding=writer.default_byte_order.get_utf_16_encoding()) + b"\0\0"
        elif encoding_type in {0, 2}:  # shift-jis
            name = self.name.encode(encoding="shift-jis") + b"\0"
        else:
            raise ValueError(f"Invalid TPF texture encoding: {encoding_type}. Must be 0, 1, or 2.")
        writer.append(name)

    def pack_data(self, writer: BinaryWriter):
        writer.fill_with_position("data_offset", obj=self)
        if self.texture_flags in {2, 3}:
            data = zlib.compress(self.data, level=7)
        else:
            data = self.data

        writer.fill("data_size", len(data), obj=self)
        writer.append(data)

    @property
    def stem(self) -> str:
        return Path(self.name).stem

    def get_dds(self) -> DDS:
        return DDS.from_bytes(self.data)

    def get_dds_format(self) -> str:
        return DDS.from_bytes(self.data).header.fourcc.decode()

    def write_dds(self, dds_path: str | Path):
        Path(dds_path).write_bytes(self.data)

    def get_png_data(self, fmt="rgba") -> bytes:
        with tempfile.TemporaryDirectory() as png_dir:
            temp_dds_path = Path(png_dir, "temp.dds")
            temp_dds_path.write_bytes(self.data)
            texconv_result = texconv("-o", png_dir, "-ft", "png", "-f", fmt, temp_dds_path)
            try:
                return Path(png_dir, "temp.png").read_bytes()
            except FileNotFoundError:
                stdout = "\n    ".join(texconv_result.stdout.decode().split("\r\n")[3:])  # drop copyright lines
                raise ValueError(f"Could not convert texture DDS to PNG:\n    {stdout}")

    def export_png(self, png_path: str | Path, fmt="rgba"):
        png_data = self.get_png_data(fmt)
        png_path.write_bytes(png_data)

    def convert_dds_format(self, output_format: str, assert_input_format: str = None) -> bool:
        """Convert `data` DDS format in place. Returns `True` if conversion succeeds."""
        dds = self.get_dds()
        current_format = dds.header.fourcc.decode()
        current_dxgi_format = dds.dxt10_header.dxgi_format if dds.dxt10_header else None
        if assert_input_format is not None and current_format != assert_input_format.encode():
            raise ValueError(
                f"TPF texture DDS format {current_format} does not match "
                f"`assert_input_format` {assert_input_format} ({current_format}"
            )
        temp_dds_path = Path(__file__).parent / "__temp__.dds"
        temp_dds_path.write_bytes(self.data)
        result = convert_dds_file(temp_dds_path, Path(__file__).parent, output_format)  # overwrite temp file
        if result.returncode == 0:
            self.data = temp_dds_path.read_bytes()
            if current_dxgi_format:
                _LOGGER.info(
                    f"Converted TPF texture {self.name} from format {current_format} "
                    f"(DXGI {current_dxgi_format}) to {output_format}."
                )
            else:
                _LOGGER.info(f"Converted TPF texture {self.name} from format {current_format} to {output_format}.")
            return True
        else:
            _LOGGER.error(
                f"Could not convert TPF texture {self.name} from format {current_format} to {output_format}.\n"
                f"   stdout: {result.stdout}\n"
                f"   stderr: {result.stderr}"
            )
            return False

    def __repr__(self) -> str:
        return (
            f"TPFTexture(\n"
            f"    name = '{self.name}'\n"
            f"    format = {self.format}\n"
            f"    texture_type = {self.texture_type.name}\n"
            f"    mipmaps = {self.mipmap_count}\n"
            f"    texture_flags = {self.texture_flags}\n"
            f"    data = <{len(self.data)} bytes>\n"
            f"    has_header = {self.header is not None}\n"
            f"    has_float_struct = {self.float_struct is not None}\n"
            f")"
        )


@dataclass(slots=True)
class TPFStruct(NewBinaryStruct):
    signature: bytes = field(**Binary(length=4, asserted=b"TPF\0"))
    _data_size: int
    file_count: int
    platform: TPFPlatform = field(**Binary(byte))
    tpf_flags: byte = field(**(Binary(asserted=[0, 1, 2, 3])))
    encoding_type: byte = field(**Binary(asserted=[0, 1, 2]))  # 2 == UTF_16, 0/1 == shift_jis_2004
    _pad1: bytes = field(**BinaryPad(1))


@dataclass(slots=True)
class TPF(BaseBinaryFile):

    textures: list[TPFTexture] = field(default_factory=list)
    platform: TPFPlatform = TPFPlatform.PC
    encoding_type: int = 0
    tpf_flags: int = 0  # non-zero value on PS3 means textures have `unk2`; unknown otherwise

    @classmethod
    def from_reader(cls, reader: BinaryReader) -> TPF:
        platform = TPFPlatform(reader.unpack_value("B", offset=0xC))
        reader.default_byte_order = ">" if platform in {TPFPlatform.Xbox360, TPFPlatform.PS3} else "<"
        tpf_struct = TPFStruct.from_bytes(reader)

        encoding = reader.get_utf_16_encoding() if tpf_struct.encoding_type == 1 else "shift_jis_2004"
        textures = [
            TPFTexture.from_tpf_reader(reader, platform, tpf_struct.tpf_flags, encoding)
            for _ in range(tpf_struct.file_count)
        ]
        return cls(textures, platform, tpf_struct.encoding, )

    def to_writer(self) -> BinaryWriter:
        """Pack TPF file to bytes."""
        byte_order = self.platform.get_byte_order()
        writer = TPFStruct.object_to_writer(self, byte_order=byte_order)

        for texture in self.textures:
            texture.to_tpf_writer(writer, self.platform, self.tpf_flags)
        for texture in self.textures:
            texture.pack_name(writer, self.encoding_type)

        data_start = writer.position
        for texture in self.textures:
            # TKGP notes: padding varies wildly across games, so don't worry about it too much.
            if len(texture.data) > 0:
                writer.pad_align(4)
            texture.pack_data(writer)
        writer.fill("data_size", writer.position - data_start, obj=self)
        return writer

    def write_unpacked_dir(self, directory=None):
        if directory is None:
            if self.path:
                directory = self.path.with_suffix(self.path.suffix + ".unpacked")
            else:
                raise ValueError("Cannot detect `directory` for unpacked binder automatically.")
        else:
            directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        texture_entries = []
        for texture in self.textures:
            texture_dict = {
                "name": texture.name,
                "format": texture.format,
                "texture_type": texture.texture_type.name,
                "mipmaps": texture.mipmap_count,
                "texture_flags": texture.texture_flags,
            }
            texture_entries.append(texture_dict)
            texture.write_dds(directory / f"{texture.stem}.dds")  # TODO: should already be '.dds', no?
        tpf_manifest = self.get_json_header()
        tpf_manifest["entries"] = texture_entries

        # NOTE: Binder manifest is always encoded in shift-JIS, not `shift_jis_2004`.
        with (directory / "tpf_manifest.json").open("w", encoding="shift-jis") as f:
            json.dump(tpf_manifest, f, indent=4)

    def get_json_header(self):
        return {
            "platform": self.platform.name,
            "encoding_type": self.encoding_type,
            "tpf_flags": self.tpf_flags,
        }

    def convert_dds_formats(self, input_format: str, output_format: str):
        """Convert all DDS files that currently have format `input_format` to `output_format`.

        Formats should look like b"DX10", b"DXT1", etc.
        """
        fail_count = 0
        total_count = 0
        for texture in self.textures:
            dds = texture.get_dds()
            if dds.header.fourcc.decode() == input_format:
                success = texture.convert_dds_format(output_format)
                total_count += 1
                if not success:
                    fail_count += 1
        if fail_count > 0:
            _LOGGER.warning(
                f"Failed to convert {fail_count} out of {total_count} textures from {input_format} to {output_format}."
            )

    def get_all_png_data(self, fmt="rgba") -> list[tp.Optional[bytes]]:
        png_datas = []
        for tex in self.textures:
            try:
                png_datas.append(tex.get_png_data(fmt))
            except ValueError as ex:
                _LOGGER.warning(str(ex))
                png_datas.append(None)
        return png_datas

    def export_to_pngs(self, png_dir_path: Path | str, fmt="rgba"):
        for tex in self.textures:
            png_name = Path(tex.name).with_suffix(".png")
            try:
                tex.export_png(png_dir_path / png_name, fmt=fmt)
            except ValueError as ex:
                _LOGGER.warning(str(ex))

    def __repr__(self) -> str:
        return (
            f"TPF(\n"
            f"    textures = <{len(self.textures)} textures>\n"
            f"    platform = {self.platform.name}\n"
            f"    encoding_type = {self.encoding_type}\n"
            f"    tpf_flags = {self.tpf_flags}\n"
            f")"
        )

    @classmethod
    def collect_tpf_entries(cls, tpfbhd_directory: str | Path) -> dict[str, BinderEntry]:
        """Build a dictionary mapping TPF entry stems to `BinderEntry` instances."""
        from soulstruct.containers import Binder

        tpf_re = re.compile(rf"(.*)\.tpf(\.dcx)?")
        tpfbhd_directory = Path(tpfbhd_directory)
        tpf_entries = {}
        for bhd_path in tpfbhd_directory.glob("*.tpfbhd"):
            bxf = Binder.from_path(bhd_path)
            for entry in bxf._entries:
                match = tpf_re.match(entry.name)
                if match:
                    tpf_entries[entry.minimal_stem] = entry
        return tpf_entries

    @classmethod
    def collect_tpf_textures(
        cls, tpfbhd_directory: str | Path, convert_formats: tp.Tuple[str, str] = None
    ) -> dict[str, TPFTexture]:
        """Build a dictionary mapping TGA texture names to `TPFTexture` instances.

        NOTE: This decompresses/unpacks every TPF in every BXF in the directory, which can be slow and redundant. Use
        `collect_tpf_entries()` above and only open the TPFs needed (since map TPFBHD TPFs should only have one DDS
        texture in them matching the TPF entry name).
        """
        from soulstruct.containers import Binder

        tpf_re = re.compile(rf"(.*)\.tpf(\.dcx)?")
        tpfbhd_directory = Path(tpfbhd_directory)
        textures = {}
        for bhd_path in tpfbhd_directory.glob("*.tpfbhd"):
            bxf = Binder.from_path(bhd_path)
            for entry in bxf._entries:
                match = tpf_re.match(entry.name)
                if match:
                    tpf = cls.from_bytes(entry.data)
                    if convert_formats is not None:
                        input_format, output_format = convert_formats
                        tpf.convert_dds_formats(input_format, output_format)
                    for texture in tpf.textures:
                        textures[texture.name] = texture
        return textures


def get_png_data(tex: TPFTexture, fmt: str):
    return tex.get_png_data(fmt=fmt)


def batch_get_tpf_texture_png_data(tpf_textures: list[TPFTexture], fmt="rgba", processes: int = None) -> list[bytes]:
    """Use multiprocessing to retrieve PNG data (converted from DDS) for a collection of `TPFTexture`s."""

    mp_args = [(tpf_texture, fmt) for tpf_texture in tpf_textures]

    with multiprocessing.Pool(processes=processes) as pool:
        png_data = pool.starmap(get_png_data, mp_args)  # blocks here until all done

    return png_data
