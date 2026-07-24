# Copyright (C) 2023 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
This script enumerates pre-built resources and updates Android.bp files:

  - $ANDROID_BUILD_TOP/device/google/cuttlefish_vmm/Android.bp
  - $ANDROID_BUILD_TOP/device/google/cuttlefish_vmm/$ARCH/Android.bp
  - $ANDROID_BUILD_TOP/device/google/cuttlefish/Android.bp

It is intended to be run manually:

  python3 $ANDROID_BUILD_TOP/device/google/cuttlefish_vmm/gen_android_bp.py

"""
import datetime
import os
import re
import sys
import textwrap
from dataclasses import dataclass
from enum import auto
from enum import Enum
from pathlib import Path
from typing import Dict
from typing import List
from typing import Iterator
from typing import TypeAlias


def tool_name() -> str:
    """Returns a short name for this generation tool."""
    return Path(__file__).name


class Architecture(Enum):
    """Host instruction set architectures."""

    AARCH64 = 'aarch64'
    X86_64 = 'x86_64'

    def dir(self) -> Path:
        "Returns the relative directory path to the specified architecture."
        return Path(f"{self.name.lower()}-linux-gnu")

    def androidbp_arch(self) -> str:
        if self == Architecture.AARCH64:
            return 'arm64'
        else:
            return 'x86_64'


# Android.bp variant value type.
Value: TypeAlias = str | Path | bool | list["Value"] | dict[str, "Value"]

DEFAULT_INDENT = "    "

def value_to_bp(value: Value, indent_depth: int = 1) -> str:
    """Returns `bp` expression for the specified value"""
    if isinstance(value, dict):
        bp = "{\n"

        bp_keyvals = []
        for k, v in value.items():
            bp_keyval = (DEFAULT_INDENT * (indent_depth + 1))
            bp_keyval += "%s: %s" % (k, value_to_bp(v, indent_depth + 1))
            bp_keyvals.append(bp_keyval)
        bp += ",\n".join(bp_keyvals)

        bp += ",\n"
        bp += (DEFAULT_INDENT * indent_depth) + "}"

        return bp
    elif isinstance(value, list):
        if len(value) == 1:
            return "[%s]" % value_to_bp(value[0])

        bp = "[\n"

        bp_keyvals = []
        for element in value:
            bp_keyval = (DEFAULT_INDENT * (indent_depth + 1))
            bp_keyval += value_to_bp(element, indent_depth + 1)
            bp_keyvals.append(bp_keyval)
        bp += ",\n".join(bp_keyvals)

        bp += ",\n"
        bp += (DEFAULT_INDENT * indent_depth) + "]"

        return bp
    elif isinstance(value, bool):
        return str(value).lower()
    elif isinstance(value, Path):
        return value_to_bp(str(value))
    else:
        return f'"{value}"'


@dataclass
class Module:
    """Android bp build rule."""

    module_type: str
    parameters: Dict[str, Value]

    @property
    def name(self) -> str:
        assert isinstance(self.parameters.get("name"), str)
        return self.parameters["name"]

    def __str__(self) -> str:
        """Returns a `.bp` string for this modules with its parameters."""
        body = "\n".join(
            f"{DEFAULT_INDENT}{k}: {value_to_bp(v)}," for k, v in self.parameters.items()
        )
        return f"{self.module_type} {{\n{body}\n}}\n"


def update_generated_section(file_path: Path, tag: str, content: str):
    """Reads a text file, matches and replaces the content between
    a start beacon and an end beacon with the specified one, and
    modifies the file in place.

    The generated content is delimited by `// Start of generated` and
    `// End of generated`. The specified content is indented the same
    way as the start beacon is.

    Args:
      file_path: path to the text file to be modified.
      tag: marks the beginning aned end of the string generated content.
      content: text to replace the content between the start and end beacons with.
    """
    # Read the contents of the text file.
    with open(file_path, "rt", encoding="utf-8") as f:
        file_contents = f.read()

    # Find the start and end beacon positions in the file contents.
    start = f"// Start of generated {tag}\n"
    end = f"// End of generated {tag}\n"

    match = re.match(
        f"^(?P<head>.*)^(?P<indent>[ \t]*){re.escape(start)}.*{re.escape(end)}(?P<tail>.*)$",
        file_contents,
        re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise ValueError(
            f"Generated content beacons {(start, end)} not matched in file {file_path}"
        )

    with open(file_path, "wt", encoding="utf-8") as f:
        f.write(f"{match.group('head')}{match.group('indent')}{start}")
        f.write(f"{match.group('indent')}// Generated by {tool_name()}\n")
        f.write(textwrap.indent(content, match.group("indent")))
        f.write(f"{match.group('indent')}{end}{match.group('tail')}")


def license() -> str:
    """Returns a license header at the current date, with generation warning."""
    current_year = datetime.datetime.now().year
    return textwrap.dedent(
        f"""\
    // Autogenerated via {tool_name()}
    //
    // Copyright (C) {current_year} The Android Open Source Project
    //
    // Licensed under the Apache License, Version 2.0 (the "License");
    // you may not use this file except in compliance with the License.
    // You may obtain a copy of the License at
    //
    //      http://www.apache.org/licenses/LICENSE-2.0
    //
    // Unless required by applicable law or agreed to in writing, software
    // distributed under the License is distributed on an "AS IS" BASIS,
    // WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    // See the License for the specific language governing permissions and
    // limitations under the License.

    """
    )


def comment(text: str) -> str:
    """Prefixes each lines with '/// ' and return the commented content."""
    return re.sub("^(?!$)", "// ", text, flags=re.MULTILINE)


def gen_android_bp4seccomp(path: Path, arch: Architecture):
    """Regenerates the specified '.bp' file for the given architecture."""

    with open(path, "wt") as out:
        subdir = Path("etc/seccomp")
        seccomp_dir = arch.dir() / subdir
        where_in_etc_on_user_machine = "cuttlefish" / arch.dir() / "seccomp"
        out.write(license())

        for path in sorted(seccomp_dir.iterdir()):
            module = Module(
                "prebuilt_usr_share_host",
                dict(
                    name=f"{path.name}_at_{arch.name.lower()}",
                    src=subdir / path.name,
                    filename=path.name,
                    sub_dir=where_in_etc_on_user_machine,
                ),
            )
            out.write(str(module))


def crosvm_binaries(arch: Architecture) -> Iterator[Path]:
    """Lists crosvm binary paths."""
    dir = arch.dir() / "bin"
    yield dir / "crosvm"
    yield dir / "gfxstream_graphics_detector"
    if arch == Architecture.AARCH64:
        yield dir / "libmem_overrides.so"
    yield dir / "libminijail.so"
    yield dir / "libgfxstream_backend.so"
    yield from dir.glob("*.so.?")


def qemu_binaries(arch: Architecture) -> Iterator[Path]:
    """Lists qemu binary paths."""
    dir = Path(f"qemu/{arch.value}-linux-gnu/bin")
    yield from dir.glob("*.so.?")
    yield from dir.glob("qemu-system*")


def swiftshader_binaries(arch: Architecture) -> Iterator[Path]:
    """Lists SwiftShader library and config paths."""
    dir = arch.dir() / "bin"
    yield dir / "libvk_swiftshader.so"
    yield dir / "vk_swiftshader_icd.json"

def gen_main_android_bp_modules() -> Iterator[Module]:
    """Returns the Modules to write in the main 'Android.bp' file."""

    for arch in Architecture:
        for path in crosvm_binaries(arch):
            name = re.sub("/bin/|/|-|_bin_", "_", str(path))
            if path.stem != "crosvm":
                name = f"{name}_for_crosvm"

            yield Module(
                "cc_prebuilt_binary",
                dict(
                    name=name,
                    srcs=[path],
                    stem=path.name,
                    relative_install_path=arch.dir(),
                    defaults=["cuttlefish_host"],
                    check_elf_files=False,
                ),
            )

    for arch in list(Architecture):
        for binary_path in qemu_binaries(arch):
            yield Module(
                "cc_prebuilt_binary",
                dict(
                    name=f"{arch.value}_linux_gnu_{binary_path.name}_binary_for_qemu",
                    srcs=[binary_path],
                    stem=binary_path.name,
                    relative_install_path=arch.dir() / "qemu",
                    defaults=["cuttlefish_host"],
                    check_elf_files=False,
                ),
            )

    for arch in list(Architecture):
        for path in swiftshader_binaries(arch):
            yield Module(
                "cc_prebuilt_binary",
                dict(
                    name=f"{arch.value}_linux_gnu_{path.name}",
                    srcs=[path],
                    stem=path.name,
                    relative_install_path=arch.dir(),
                    defaults=["cuttlefish_host"],
                    check_elf_files=False,
                ),
            )

    resource_paths = [
        Path(f"efi-virtio.rom"),
        Path(f"keymaps/en-us"),
        Path(f"opensbi-riscv64-generic-fw_dynamic.bin"),
    ]

    for arch in list(Architecture):
        for resource_path in resource_paths:
            base_name = resource_path.name
            subdir = f"qemu/{arch.value}-linux-gnu" / resource_path.parents[0]
            yield Module(
                "prebuilt_usr_share_host",
                dict(
                    name=f"{arch.value}_{base_name}_resource_for_qemu",
                    src=f"qemu/{arch.value}-linux-gnu/usr/share/qemu/{resource_path}",
                    filename=base_name,
                    sub_dir=subdir,
                ),
            )

    # Add another version of crosvm that goes into a `prebuilts` subdirectory
    # to avoid conflicting with the existing crosvm that is built from source
    # from `external/crosvm` and is also placed in `x86_64-linux-gnu`. This
    # prebuilt version of crosvm is used for the vhost-user-gpu device that
    # needs to be able to load userspace GPU drivers (OpenGL / Vulkan) that
    # are built with glibc instead of Android's bionic/musl.
    crosvm_prebuilts_basenames = set()
    for arch in Architecture:
        for path in crosvm_binaries(arch):
            crosvm_prebuilts_basenames.add(str(os.path.basename(path)))

    for prebuilt_basename in crosvm_prebuilts_basenames:
        name = re.sub("/bin/|/|-|_bin_", "_", prebuilt_basename)
        name = f"cuttlefish_vmm_bin_prebuilts_{name}"

        module_archs = dict()
        for arch in Architecture:
            arch_dir = arch.dir() / "bin"
            arch_prebuilt_path = arch_dir / prebuilt_basename

            if not os.path.exists(arch_prebuilt_path):
                continue

            module_archs[arch.androidbp_arch()] = dict(
                srcs=[arch_prebuilt_path]
            )

        yield Module(
            "cc_prebuilt_binary",
            dict(
                name=name,
                arch=module_archs,
                stem=prebuilt_basename,
                relative_install_path="prebuilts",
                defaults=["cuttlefish_host"],
                check_elf_files=False,
            ),
        )


def gen_main_android_bp_file(android_bp_path: Path, modules: List[Module]):
    """Writes the main 'Android.bp' file with the specified modules."""

    disclamer = f"""\
        // NOTE: Using cc_prebuilt_binary because cc_prebuilt_library will add
        //       unwanted .so file extensions when installing shared libraries

        """
    crosvm_comment = """\
        // Note: This is commented out to avoid a conflict with the binary built
        // from external/crosvm. This should be uncommented out when backporting to
        // older branches with just use the prebuilt and which do not build from
        // source.
        """

    arch_dependent_graphics_detector = """\
cc_prebuilt_binary {
    name: "graphics_detector",
    stem: "graphics_detector",
    arch: {
        arm64: {
            srcs: [
                "aarch64-linux-gnu/bin/gfxstream_graphics_detector",
            ],
        },
        x86_64: {
            srcs: [
                "x86_64-linux-gnu/bin/gfxstream_graphics_detector",
            ],
        },
    },
    defaults: ["cuttlefish_host"],
    check_elf_files: false,
}
        """


    with open(android_bp_path, "wt") as out:
        out.write(license())
        out.write(textwrap.dedent(disclamer))

        sort_key = lambda m: (
            m.name,
            m.parameters["name"].rsplit("_")[-1],
            m.parameters["name"],
        )
        for module in sorted(modules, key=sort_key):
            module_text = str(module)
            if module.parameters["name"] == "x86_64_linux_gnu_crosvm":
                out.write(textwrap.dedent(crosvm_comment))
                module_text = comment(module_text)
            out.write(module_text)
            out.write("\n")

        out.write(arch_dependent_graphics_detector)


def generate_all_cuttlefish_host_package_android_bp(path: Path, modules: list[Module]):
    """Updates the list of module in 'device/google/cuttlefish/Android.bp'."""

    def update_list(list_name: str, modules:list[Module]):
        names = sorted(m.parameters["name"] for m in modules)
        text = f"{list_name} = {value_to_bp(names)}\n"
        update_generated_section(path, list_name, text)

    for arch in list(Architecture):
        qemu_binaries = [m for m in modules if m.name.endswith("_binary_for_qemu") and m.name.startswith(arch.value)]
        qemu_resources = [m for m in modules if m.name.endswith("_resource_for_qemu") and m.name.startswith(arch.value)]

        update_list(f"qemu_{arch.value}_linux_gnu_binary", qemu_binaries)
        update_list(f"qemu_{arch.value}_linux_gnu_resource", qemu_resources)


def main(argv):
    if len(argv) != 1:
        print(f"Usage error: {argv[0]} does not accept any argument.")
        return 1

    # Set the current directory to the script location.
    os.chdir(Path(__file__).parent)

    modules = list(gen_main_android_bp_modules())
    gen_main_android_bp_file(Path("Android.bp"), modules)

    generate_all_cuttlefish_host_package_android_bp(
        Path("../cuttlefish/build/Android.bp"), modules
    )

    for arch in Architecture:
        gen_android_bp4seccomp(arch.dir() / "Android.bp", arch)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
