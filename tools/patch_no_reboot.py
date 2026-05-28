#!/usr/bin/env python3
"""Create ATBM6441 no-reboot firmware artifacts from a flash dump.

The input must be the corrected little-endian flash image, not the initial
word-swapped dump produced by early read attempts.
"""

from __future__ import annotations

import argparse
import hashlib
import zlib
from pathlib import Path


CODE1_START = 0x010000
CODE1_END = 0x040000
CODE2_START = 0x040000
CODE2_END = 0x1FFE18
CODE2_ZLIB_OFFSET = 0x284000
IOT_UPDATE_TRAILER_SIZE = 24
IOT_UPDATE_CHECKSUM_OFFSET = 8
BOOT_VALID_FLAG = 0x32A7

RETURN_STUB = bytes.fromhex("8280010001000100")

PATCHES = (
    ("atbm_hal_reset_cpu_path", 0x076332, bytes.fromhex("1783f0ffe702c30a")),
    ("hardware_reboot_path", 0x076478, bytes.fromhex("1783f0ffe70263f6")),
    ("wdt_rtc_trigger_reboot", 0x0979EE, bytes.fromhex("1773eeffe702039f")),
    ("wdt_rtc_status_or_reboot_path", 0x097A46, bytes.fromhex("1773eeffe702e397")),
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def consume_zlib_stream(data: bytes) -> tuple[bytes, int]:
    decompressor = zlib.decompressobj()
    plain = decompressor.decompress(data)
    if not decompressor.eof:
        raise ValueError("CODE2 zlib mirror did not contain a complete stream")
    consumed = len(data) - len(decompressor.unused_data)
    return plain, consumed


def fw_chksum(data: bytes) -> int:
    """Match the SDK fw_chksum() little-endian 16-bit word sum."""
    total = 0
    end = len(data) - (len(data) % 2)
    for i in range(0, end, 2):
        total = (total + data[i] + (data[i + 1] << 8)) & 0xFFFF
    if len(data) % 2:
        total = (total + data[-1]) & 0xFFFF
    return total


def update_code2_trailer(code1: bytes, code2: bytes) -> tuple[bytes, str]:
    """Recalculate the fw_update2 trailer checksum after patching CODE2."""
    if len(code2) < IOT_UPDATE_TRAILER_SIZE:
        raise ValueError("CODE2 image is too small to contain an update trailer")

    patched = bytearray(code2)
    trailer_offset = len(patched) - IOT_UPDATE_TRAILER_SIZE
    flag = int.from_bytes(patched[trailer_offset : trailer_offset + 4], "little")
    if flag != BOOT_VALID_FLAG:
        raise ValueError(
            f"CODE2 update trailer flag was 0x{flag:08x}, "
            f"expected 0x{BOOT_VALID_FLAG:08x}"
        )

    checksum_offset = trailer_offset + IOT_UPDATE_CHECKSUM_OFFSET
    old_checksum = int.from_bytes(patched[checksum_offset : checksum_offset + 4], "little")
    patched[checksum_offset : checksum_offset + 4] = b"\x00\x00\x00\x00"
    new_checksum = (fw_chksum(code1) + fw_chksum(patched)) & 0xFFFF
    patched[checksum_offset : checksum_offset + 4] = new_checksum.to_bytes(4, "little")

    return (
        bytes(patched),
        f"CODE2 update trailer checksum: 0x{old_checksum:04x} -> 0x{new_checksum:04x}",
    )


def patch_image(image: bytearray, force: bool = False) -> list[str]:
    notes: list[str] = []
    for name, offset, old_bytes in PATCHES:
        current = bytes(image[offset : offset + len(RETURN_STUB)])
        if current == RETURN_STUB:
            notes.append(f"{name} @ 0x{offset:06x}: already patched")
            continue
        if current != old_bytes and not force:
            raise ValueError(
                f"{name} @ 0x{offset:06x} was {current.hex()}, "
                f"expected {old_bytes.hex()}"
            )
        image[offset : offset + len(RETURN_STUB)] = RETURN_STUB
        notes.append(f"{name} @ 0x{offset:06x}: {current.hex()} -> {RETURN_STUB.hex()}")
    return notes


def write_outputs(input_path: Path, output_dir: Path, force: bool) -> None:
    image = bytearray(input_path.read_bytes())
    if len(image) <= CODE2_ZLIB_OFFSET:
        raise ValueError("Input image is too small to contain the CODE2 zlib mirror")

    notes = patch_image(image, force=force)

    code1 = bytes(image[CODE1_START:CODE1_END])
    code2, trailer_note = update_code2_trailer(
        code1,
        bytes(image[CODE2_START:CODE2_END]),
    )
    image[CODE2_START:CODE2_END] = code2
    notes.append(trailer_note)

    mirror_plain, mirror_consumed = consume_zlib_stream(bytes(image[CODE2_ZLIB_OFFSET:]))
    if len(mirror_plain) != len(code2):
        raise ValueError(
            f"CODE2 mirror expands to {len(mirror_plain)} bytes, expected {len(code2)}"
        )

    compressed_code2 = zlib.compress(code2, level=9)
    if len(compressed_code2) > mirror_consumed:
        raise ValueError(
            f"Patched CODE2 zlib stream is too large: "
            f"{len(compressed_code2)} > {mirror_consumed}"
        )

    image[CODE2_ZLIB_OFFSET : CODE2_ZLIB_OFFSET + len(compressed_code2)] = compressed_code2
    image[
        CODE2_ZLIB_OFFSET + len(compressed_code2) : CODE2_ZLIB_OFFSET + mirror_consumed
    ] = b"\xff" * (mirror_consumed - len(compressed_code2))
    notes.append(
        f"CODE2 zlib mirror @ 0x{CODE2_ZLIB_OFFSET:06x}: "
        f"{mirror_consumed} bytes -> {len(compressed_code2)} bytes"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    firmware_path = output_dir / "firmware_no_reboot.bin"
    code1_path = output_dir / "code1_original.bin"
    code2_path = output_dir / "code2_no_reboot.bin"
    code2_zlib_path = output_dir / "code2_no_reboot_zlib_284000.bin"
    manifest_path = output_dir / "no_reboot_patch_manifest.txt"

    firmware_path.write_bytes(image)
    code1_path.write_bytes(bytes(image[CODE1_START:CODE1_END]))
    code2_path.write_bytes(code2)
    code2_zlib_path.write_bytes(compressed_code2)

    manifest_lines = [
        *notes,
        f"firmware_no_reboot.bin sha256 {sha256(firmware_path)}",
        f"code1_original.bin sha256 {sha256(code1_path)}",
        f"code2_no_reboot.bin sha256 {sha256(code2_path)}",
    ]
    manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    print(f"Wrote {firmware_path}")
    print(f"Wrote {code1_path}")
    print(f"Wrote {code2_path}")
    print(f"Wrote {manifest_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        type=Path,
        help="Corrected little-endian 4MB flash dump, e.g. firmware_dump_le.bin",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("firmware_analysis"),
        help="Directory for patched firmware artifacts",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Patch even if the original bytes do not match the known dump",
    )
    args = parser.parse_args()
    write_outputs(args.input, args.output_dir, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
