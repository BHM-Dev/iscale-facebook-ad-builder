"""Crop (never stretch) an image to a target aspect ratio, anchored along
whichever axis actually gets trimmed.

Built for the Ad Builder's Feed (1:1) <-> Stories (9:16) auto/manual duplicate
feature: reusing the exact same image for both placements previously meant
either Meta's own placement-level auto-crop (mediocre, sometimes padded) or a
naive stretch. This produces a real, correctly-cropped, non-distorted image of
the right dimensions up front, with a user-adjustable anchor for when the
default center crop cuts off something important.

Shares the same crop-then-resize shape as text_overlay_service._crop_to_target
(that one is center-only, built for Pexels stock photos) — this version adds
the anchor parameter needed for a user-facing reposition control.
"""
from io import BytesIO

from PIL import Image

# 0.0 = start (left/top), 0.5 = center, 1.0 = end (right/bottom) along the
# axis being cropped.
_ANCHOR_FRACTIONS = {'start': 0.0, 'center': 0.5, 'end': 1.0}


def crop_to_aspect(image_bytes: bytes, target_w: int, target_h: int, anchor: str = 'center') -> tuple[bytes, str]:
    """Crop image_bytes to target_w:target_h, then resize to those exact
    pixel dimensions, and return (JPEG bytes, crop_axis).

    Crops width (anchor picks left/center/right) when the source is
    relatively wider than the target — e.g. a square Feed image being cut
    down for vertical Stories. Crops height (anchor picks top/center/bottom)
    when the source is relatively taller — e.g. a Stories image being cut
    down for square Feed. Never stretches or distorts.

    crop_axis is 'width', 'height', or 'none' (source already matched the
    target ratio) — which axis actually got trimmed, driven purely by the
    source image's own dimensions vs. the target ratio, NOT by the Feed/
    Stories format label. A landscape photo duped to Feed still gets its
    WIDTH trimmed even though Feed is the "vertical-labeled" direction, so
    callers needing an accurate Left/Right vs. Top/Bottom anchor-picker
    label must use this rather than inferring the axis from format.
    """
    if anchor not in _ANCHOR_FRACTIONS:
        raise ValueError(f"anchor must be one of {sorted(_ANCHOR_FRACTIONS)}, got {anchor!r}")
    anchor_fraction = _ANCHOR_FRACTIONS[anchor]

    img = Image.open(BytesIO(image_bytes))
    # Drop alpha/palette before JPEG save — flatten onto white rather than
    # letting Pillow error on save or silently discard transparency oddly.
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGBA') if img.mode in ('P', 'LA') else img
        if img.mode == 'RGBA':
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        else:
            img = img.convert('RGB')

    src_w, src_h = img.size
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if abs(src_ratio - target_ratio) < 0.01:
        cropped = img
        crop_axis = 'none'
    elif src_ratio > target_ratio:
        # Source is relatively wider than the target — crop left/right, keep full height.
        new_w = max(1, int(round(src_h * target_ratio)))
        max_left = src_w - new_w
        left = int(round(max_left * anchor_fraction))
        cropped = img.crop((left, 0, left + new_w, src_h))
        crop_axis = 'width'
    else:
        # Source is relatively taller than the target — crop top/bottom, keep full width.
        new_h = max(1, int(round(src_w / target_ratio)))
        max_top = src_h - new_h
        top = int(round(max_top * anchor_fraction))
        cropped = img.crop((0, top, src_w, top + new_h))
        crop_axis = 'height'

    resized = cropped.resize((target_w, target_h), Image.LANCZOS)
    buf = BytesIO()
    resized.save(buf, format='JPEG', quality=90)
    return buf.getvalue(), crop_axis
