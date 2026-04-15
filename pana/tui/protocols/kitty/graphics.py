"""Kitty graphics protocol helpers."""
from __future__ import annotations

import random

from pana.tui.protocols.kitty.sequences import KITTY_GRAPHICS_PREFIX, KITTY_GRAPHICS_SUFFIX

_CHUNK_SIZE = 4096


def is_kitty_image_line(line: str) -> bool:
    """Return True if *line* contains a Kitty graphics sequence."""
    if line.startswith(KITTY_GRAPHICS_PREFIX):
        return True
    return KITTY_GRAPHICS_PREFIX in line



def allocate_image_id() -> int:
    """Generate a random image ID for the Kitty graphics protocol."""
    return random.randint(1, 0xFFFFFFFF)



def encode_kitty(
    base64_data: str,
    *,
    columns: int | None = None,
    rows: int | None = None,
    image_id: int | None = None,
) -> str:
    """Encode image data using the Kitty graphics protocol."""
    params: list[str] = ["a=T", "f=100", "q=2"]
    if columns is not None:
        params.append(f"c={columns}")
    if rows is not None:
        params.append(f"r={rows}")
    if image_id is not None:
        params.append(f"i={image_id}")

    if len(base64_data) <= _CHUNK_SIZE:
        return (
            f"{KITTY_GRAPHICS_PREFIX}{','.join(params)};"
            f"{base64_data}{KITTY_GRAPHICS_SUFFIX}"
        )

    chunks: list[str] = []
    offset = 0
    is_first = True

    while offset < len(base64_data):
        chunk = base64_data[offset : offset + _CHUNK_SIZE]
        is_last = offset + _CHUNK_SIZE >= len(base64_data)

        if is_first:
            chunks.append(
                f"{KITTY_GRAPHICS_PREFIX}{','.join(params)},m=1;"
                f"{chunk}{KITTY_GRAPHICS_SUFFIX}"
            )
            is_first = False
        elif is_last:
            chunks.append(f"{KITTY_GRAPHICS_PREFIX}m=0;{chunk}{KITTY_GRAPHICS_SUFFIX}")
        else:
            chunks.append(f"{KITTY_GRAPHICS_PREFIX}m=1;{chunk}{KITTY_GRAPHICS_SUFFIX}")

        offset += _CHUNK_SIZE

    return "".join(chunks)



def delete_kitty_image(image_id: int) -> str:
    """Delete a Kitty graphics image by ID."""
    return f"{KITTY_GRAPHICS_PREFIX}a=d,d=I,i={image_id}{KITTY_GRAPHICS_SUFFIX}"



def delete_all_kitty_images() -> str:
    """Delete all visible Kitty graphics images."""
    return f"{KITTY_GRAPHICS_PREFIX}a=d,d=A{KITTY_GRAPHICS_SUFFIX}"
