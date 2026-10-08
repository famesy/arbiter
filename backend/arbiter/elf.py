"""A small read-only ELF reader: symbols, and memory reads by virtual address.

Enough to look up a symbol and to follow pointers through initialised data, as
the console detection and the Zephyr shell command extraction need. Handles
ELF32/64, little and big endian. No dependency on pyelftools."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

SHT_SYMTAB = 2
SHT_NOBITS = 8
SHF_ALLOC = 0x2
EM_X86_64 = 62


class ElfError(ValueError):
    pass


@dataclass(frozen=True)
class Section:
    addr: int
    offset: int
    size: int
    type: int
    flags: int


class Elf:
    def __init__(self, data: bytes):
        if data[:4] != b"\x7fELF" or len(data) < 0x34:
            raise ElfError("not an ELF file")
        self.data = data
        self.is64 = data[4] == 2
        self.end = "<" if data[5] == 1 else ">"
        self.ptr_size = 8 if self.is64 else 4
        (self.machine,) = struct.unpack_from(self.end + "H", data, 0x12)
        self.sections = [self._section(i) for i in range(self._shnum())]
        self._symbols: dict[str, int] | None = None

    @classmethod
    def load(cls, path: Path) -> Elf:
        try:
            return cls(Path(path).read_bytes())
        except OSError as e:
            raise ElfError(str(e)) from None
        except struct.error:
            raise ElfError("truncated ELF file") from None

    # ------------------------------------------------------------- headers
    def _shnum(self) -> int:
        if self.is64:
            (self._shoff,) = struct.unpack_from(self.end + "Q", self.data, 0x28)
            self._shentsize, shnum = struct.unpack_from(self.end + "HH", self.data, 0x3A)
        else:
            (self._shoff,) = struct.unpack_from(self.end + "I", self.data, 0x20)
            self._shentsize, shnum = struct.unpack_from(self.end + "HH", self.data, 0x2E)
        return int(shnum)

    def _raw_section(self, i: int) -> tuple[int, ...]:
        fmt = "IIQQQQIIQQ" if self.is64 else "IIIIIIIIII"
        return struct.unpack_from(self.end + fmt, self.data, self._shoff + i * self._shentsize)

    def _section(self, i: int) -> Section:
        _name, typ, flags, addr, off, size, _link, _info, _align, _entsize = self._raw_section(i)
        return Section(addr, off, size, typ, flags)

    # ------------------------------------------------------------- symbols
    @property
    def symbols(self) -> dict[str, int]:
        if self._symbols is None:
            self._symbols = self._read_symbols()
        return self._symbols

    def _read_symbols(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for i in range(len(self.sections)):
            _n, typ, _f, _a, off, size, link, _i, _al, entsize = self._raw_section(i)
            if typ != SHT_SYMTAB or not entsize:
                continue
            stroff = self.sections[link].offset
            for j in range(size // entsize):
                o = off + j * entsize
                if self.is64:
                    st_name, _info, _other, _shndx, value, _sz = struct.unpack_from(
                        self.end + "IBBHQQ", self.data, o
                    )
                else:
                    st_name, value, _sz, _info, _other, _shndx = struct.unpack_from(
                        self.end + "IIIBBH", self.data, o
                    )
                if st_name:
                    name_end = self.data.find(b"\x00", stroff + st_name)
                    name = self.data[stroff + st_name : name_end].decode("latin-1")
                    out.setdefault(name, int(value))
        return out

    def symbol(self, name: str) -> int | None:
        return self.symbols.get(name)

    # -------------------------------------------------------------- memory
    def read(self, addr: int, size: int) -> bytes:
        """Bytes at a virtual address, from an allocated section that has file contents."""
        for s in self.sections:
            if s.flags & SHF_ALLOC and s.type != SHT_NOBITS and s.addr <= addr < s.addr + s.size:
                if addr + size > s.addr + s.size:
                    break
                o = s.offset + addr - s.addr
                return self.data[o : o + size]
        raise ElfError(f"address {addr:#x} is not in initialised memory")

    def ptr(self, addr: int) -> int:
        fmt = "Q" if self.is64 else "I"
        return int(struct.unpack(self.end + fmt, self.read(addr, self.ptr_size))[0])

    def u8(self, addr: int) -> int:
        return self.read(addr, 1)[0]

    def cstr(self, addr: int, limit: int = 4096) -> str:
        for s in self.sections:
            if s.flags & SHF_ALLOC and s.type != SHT_NOBITS and s.addr <= addr < s.addr + s.size:
                o = s.offset + addr - s.addr
                stop = min(o + limit, s.offset + s.size)
                nul = self.data.find(b"\x00", o, stop)
                if nul < 0:
                    raise ElfError(f"no string end at {addr:#x}")
                return self.data[o:nul].decode("utf-8", errors="replace")
        raise ElfError(f"address {addr:#x} is not in initialised memory")


def elf_symbol(path: Path, name: str) -> int | None:
    """The value of a symbol from .symtab, or None if the file or symbol is missing."""
    try:
        return Elf.load(path).symbol(name)
    except ElfError:
        return None
