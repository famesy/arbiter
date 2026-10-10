"""Read the shell commands a Zephyr image registers, straight from its ELF.

The human console can then offer completion and help even when the firmware is
built without tab completion or help text on the device. Nothing runs on the
board: the command tables are static data in the image.

Zephyr keeps them like this (include/zephyr/shell/shell.h):

* Root commands (`SHELL_CMD_REGISTER`) are an iterable section of
  `union shell_cmd_entry`, a single pointer each, between the linker symbols
  `_shell_root_cmds_list_start` and `_shell_root_cmds_list_end`. Each points to a
  `struct shell_static_entry {syntax, help, subcmd, handler, args, padding}`.
* A static subcommand set (`SHELL_STATIC_SUBCMD_SET_CREATE`) is a
  `union shell_cmd_entry` pointing to an array of entries ended by a NULL syntax.
* A section subcommand set (`SHELL_SUBCMD_SET_CREATE` + `SHELL_SUBCMD_ADD`) lives in
  the `shell_subcmds` section: `subcmd` points at an empty first entry and the
  commands follow it, again until a NULL syntax.
* Dynamic subcommands (`SHELL_DYNAMIC_CMD_CREATE`) are built at run time, so only
  the fact that they exist is reported.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from .console.detect import image_dirs
from .elf import EM_X86_64, Elf, ElfError

MAX_DEPTH = 8
# Zephyr 4.x SHELL_HELP(): the help pointer is a struct shell_cmd_help {magic, description,
# usage} starting with this word instead of a string.
STRUCTURED_HELP_MAGIC = 0x86D20BC4
MAX_CHILDREN = 1024


@dataclass
class ShellCommand:
    name: str
    help: str | None = None
    usage: str | None = None  # from structured help (SHELL_HELP), when the image has it
    mandatory: int = 0  # argument counts include the command itself, as in Zephyr
    optional: int = 0
    dynamic: bool = False  # subcommands are generated at run time and not listed
    subcommands: list[ShellCommand] = field(default_factory=list)


@dataclass
class ShellCommands:
    available: bool
    reason: str = ""
    image: str | None = None
    elf: str | None = None
    commands: list[ShellCommand] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def count(self) -> int:
        def walk(cmds: list[ShellCommand]) -> int:
            return sum(1 + walk(c.subcommands) for c in cmds)

        return walk(self.commands)


class _Reader:
    def __init__(self, elf: Elf):
        self.elf = elf
        p = elf.ptr_size
        # syntax, help, subcmd, handler, then struct shell_static_args (4 bytes), aligned
        size = -(-(4 * p + 4) // p) * p
        if elf.is64 and elf.machine == EM_X86_64:
            size += 24  # Z_SHELL_STATIC_ENTRY_PADDING on native_sim 64-bit and x86_64
        self.entry_size = size
        self.order: Literal["little", "big"] = "big" if elf.end == ">" else "little"
        self.dynamic = self._range("shell_dynamic_subcmds")
        self.section = self._range("shell_subcmds")

    def _range(self, name: str) -> tuple[int, int]:
        return section_range(self.elf, name)

    @staticmethod
    def _within(addr: int, rng: tuple[int, int]) -> bool:
        return rng[0] <= addr < rng[1]

    def entry(self, addr: int, depth: int) -> ShellCommand | None:
        e, p = self.elf, self.elf.ptr_size
        syntax = e.ptr(addr)
        if not syntax:
            return None
        help_ptr, subcmd = e.ptr(addr + p), e.ptr(addr + 2 * p)
        cmd = ShellCommand(
            name=e.cstr(syntax, 256),
            mandatory=e.u8(addr + 4 * p),
            optional=e.u8(addr + 4 * p + 1),
        )
        if help_ptr:
            cmd.help, cmd.usage = self.help(help_ptr)
        if subcmd:
            if self._within(subcmd, self.dynamic):
                cmd.dynamic = True
            elif depth < MAX_DEPTH:
                cmd.subcommands = self.children(subcmd, depth + 1)
        return cmd

    def help(self, addr: int) -> tuple[str | None, str | None]:
        """(description, usage) of a help pointer: a plain string, or structured help."""
        e, p = self.elf, self.elf.ptr_size
        if e.read(addr, 4) == STRUCTURED_HELP_MAGIC.to_bytes(4, self.order):
            desc, usage = e.ptr(addr + p), e.ptr(addr + 2 * p)  # magic is padded to a pointer
            return (e.cstr(desc) if desc else None, e.cstr(usage) if usage else None)
        return e.cstr(addr), None

    def children(self, subcmd: int, depth: int) -> list[ShellCommand]:
        if self._within(subcmd, self.section):
            first = subcmd + self.entry_size  # the set's own entry is an empty marker
        else:
            first = self.elf.ptr(subcmd)
        if not first:
            return []
        out = []
        for i in range(MAX_CHILDREN):
            cmd = self.entry(first + i * self.entry_size, depth)
            if cmd is None:
                break
            out.append(cmd)
        return out

    def roots(self) -> list[ShellCommand]:
        start, end = self._range("shell_root_cmds")
        p = self.elf.ptr_size
        out = []
        for addr in range(start, end, p):
            cmd = self.entry(self.elf.ptr(addr), 1)
            if cmd is not None:
                out.append(cmd)
        return out


def section_range(elf: Elf, name: str) -> tuple[int, int]:
    """Bounds of an iterable section: Zephyr's linker script names them
    _<name>_list_start/_end; a plain GNU ld link gives __start_<name>/__stop_<name>."""
    for start_sym, end_sym in (
        (f"_{name}_list_start", f"_{name}_list_end"),
        (f"__start_{name}", f"__stop_{name}"),
    ):
        start, end = elf.symbol(start_sym), elf.symbol(end_sym)
        if start is not None and end is not None:
            return start, end
    return 0, 0


def from_elf(path: Path) -> ShellCommands:
    try:
        elf = Elf.load(path)
        if section_range(elf, "shell_root_cmds") == (0, 0):
            return ShellCommands(False, "the image has no shell", elf=str(path))
        cmds = _Reader(elf).roots()
    except ElfError as e:
        return ShellCommands(False, f"cannot read shell commands: {e}", elf=str(path))
    if not cmds:
        # Zephyr's linker script defines the section bounds whether or not the shell is
        # built in, so an image without a shell has an empty section, not a missing one.
        return ShellCommands(False, "the image has no shell", elf=str(path))
    return ShellCommands(True, elf=str(path), commands=cmds)


def shell_disabled(zephyr_dir: Path) -> bool:
    """The image's .config shows it was built without CONFIG_SHELL. False when there is no
    .config to tell, so a missing file never invents a reason."""
    try:
        text = (zephyr_dir / ".config").read_text(errors="replace")
    except OSError:
        return False
    return "CONFIG_SHELL=y" not in text.splitlines()


def from_build(build_dir: Path) -> ShellCommands:
    """Commands of the build's default image (the application with sysbuild)."""
    build_dir = Path(build_dir)
    images = image_dirs(build_dir) or [("", build_dir)]
    name, d = images[0]
    image = name if (build_dir / "domains.yaml").exists() else None
    for f in ("zephyr.elf", "zephyr.exe"):
        elf = d / "zephyr" / f
        if elf.exists():
            res = from_elf(elf)
            res.image = image
            if not res.available and shell_disabled(d / "zephyr"):
                res.reason = "the image was built without CONFIG_SHELL"
            return res
    return ShellCommands(False, f"no zephyr.elf in {d / 'zephyr'}", image=image)


def normalize(record: dict[str, Any] | None) -> dict[str, Any] | None:
    """A stored record from before empty command tables counted as no shell."""
    if record and record.get("available") and not record.get("commands"):
        record = {**record, "available": False, "reason": "the image has no shell"}
    return record
