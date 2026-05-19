"""
Text overlay compositing for ad images.

Matches the commercial-insurance ad style Joel uses:
  - ExtraBold Italic headline (white + black stroke) in the lower-left
  - Optional offer line below ("From $24.95/Month" etc.)
  - Orange rounded-pill CTA button
  - Optional logo badge top-right in white rounded rect
  - No gradient background needed — stroke handles any background

Fonts: Montserrat ExtraBoldItalic + ExtraBold + Bold
Downloaded once to backend/fonts/ and cached on disk.
"""

import io
import logging
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# ── Font management ────────────────────────────────────────────────────────────

FONTS_DIR = Path(__file__).parent.parent.parent / "fonts"
FONTS_DIR.mkdir(exist_ok=True)

_FONT_URLS = {
    "Montserrat-ExtraBoldItalic.ttf": (
        "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/"
        "Montserrat-ExtraBoldItalic.ttf"
    ),
    "Montserrat-ExtraBold.ttf": (
        "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/"
        "Montserrat-ExtraBold.ttf"
    ),
    "Montserrat-Bold.ttf": (
        "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/"
        "Montserrat-Bold.ttf"
    ),
}


def _ensure_fonts() -> bool:
    """Download missing Montserrat font files. Returns True if all fonts are ready."""
    all_ready = True
    for filename, url in _FONT_URLS.items():
        path = FONTS_DIR / filename
        if not path.exists():
            try:
                logger.info("Downloading font %s ...", filename)
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                path.write_bytes(r.content)
                logger.info("Font %s downloaded (%d bytes)", filename, len(r.content))
            except Exception as exc:
                logger.warning("Could not download font %s: %s — falling back to default", filename, exc)
                all_ready = False
    return all_ready


def _load_font(filename: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a Montserrat font by filename; falls back to PIL default if unavailable.

    Pillow >= 10 dropped `textbbox` / `stroke_width` support for the legacy bitmap
    font returned by `ImageFont.load_default()` with no arguments.  We try to pass
    `size=` (added in 10.1.0) so we always get a FreeTypeFont-compatible object back.
    If that also fails (Pillow 10.0.x), we return a small TrueType built-in via a
    known-good system path.  If nothing works we raise so the caller can surface a
    useful error rather than a confusing AttributeError later.
    """
    path = FONTS_DIR / filename
    if path.exists():
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            pass
    # Try Pillow 10.1+ load_default(size=) which returns a FreeTypeFont
    try:
        return ImageFont.load_default(size=size)  # type: ignore[call-arg]
    except TypeError:
        pass
    # Last resort: raise so the caller knows fonts are unavailable
    raise RuntimeError(
        f"Font '{filename}' could not be loaded and no FreeType fallback is available. "
        "Ensure Montserrat fonts were downloaded to backend/fonts/ or upgrade to Pillow >= 10.1.0."
    )


# Pre-fetch fonts at module import so they're ready before the first request.
_ensure_fonts()


# ── Layout helpers ─────────────────────────────────────────────────────────────

def _wrap_to_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """Word-wrap `text` so each line fits within `max_width` pixels."""
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines or [text]


def _fit_headline_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_size: int,
    min_size: int,
    font_file: str,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Find the largest font size where all wrapped lines fit within max_width."""
    for size in range(max_size, min_size - 1, -4):
        font = _load_font(font_file, size)
        lines = _wrap_to_width(draw, text, font, max_width)
        if all(draw.textbbox((0, 0), line, font=font)[2] <= max_width for line in lines):
            return font, lines
    font = _load_font(font_file, min_size)
    return font, _wrap_to_width(draw, text, font, max_width)


# ── Public API ─────────────────────────────────────────────────────────────────

# Orange button colour matching the reference ad (#F5970A)
_CTA_ORANGE = (245, 151, 10, 255)
_WHITE      = (255, 255, 255, 255)
_BLACK_STROKE = (0, 0, 0, 220)


def _crop_to_target(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """
    Center-crop img to the target aspect ratio, then resize to target_w × target_h.

    Pexels returns landscape photos even for 1:1 requests (it has no square
    orientation filter). Without this step the saved image has letterbox bars or
    wrong aspect ratio, making text and logo positions look wrong.
    """
    src_w, src_h = img.size
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if abs(src_ratio - target_ratio) < 0.01:
        # Already the right ratio — just resize
        return img.resize((target_w, target_h), Image.LANCZOS)

    if src_ratio > target_ratio:
        # Source is too wide — crop sides
        new_w = int(src_h * target_ratio)
        left = (src_w - new_w) // 2
        img = img.crop((left, 0, left + new_w, src_h))
    else:
        # Source is too tall — crop top/bottom
        new_h = int(src_w / target_ratio)
        top = (src_h - new_h) // 2
        img = img.crop((0, top, src_w, top + new_h))

    return img.resize((target_w, target_h), Image.LANCZOS)


def apply_text_overlay(
    image_bytes: bytes,
    headline: str = "",        # unused — headline goes in Meta ad copy, not the image
    offer_line: str = "",
    cta_text: str = "",        # unused — CTA goes in Meta ad copy, not the image
    logo_url: str | None = None,
    niche_line: str = "",
    target_width: int = 0,
    target_height: int = 0,
) -> bytes:
    """
    Composite a minimal overlay onto `image_bytes` (PNG/JPEG).

    The image carries only what belongs on the creative itself:
      - Top-right:  logo badge (white rounded rect) if logo_url provided
      - Lower-left: niche_line — the hero text (e.g. "Winery Business Insurance")
      - Below that: offer_line — supporting line (e.g. "From $24.95/Month")

    Headline and CTA are NOT rendered here — they belong in Meta's ad copy
    fields (primary_text, headline, call_to_action), not baked into the image.

    target_width / target_height: if provided, center-crop and resize the source
    image to these exact dimensions before compositing. This prevents letterboxing
    when Pexels returns landscape photos for a square 1:1 request.

    Returns PNG bytes of the composited image.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

    # Crop/resize to target canvas if dimensions were specified
    if target_width > 0 and target_height > 0:
        img = _crop_to_target(img, target_width, target_height)

    W, H = img.size

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    LEFT = int(W * 0.055)
    text_max_w = int(W * 0.60)
    gap_after_niche = int(H * 0.014)

    # Anchor text block in the lower-left.
    # With only niche + offer (no headline or CTA), start lower so
    # the photo subject stays visible and text doesn't crowd the middle.
    aspect = H / W
    if aspect > 1.6:      # 9:16 story
        y = int(H * 0.62)
    elif aspect > 1.15:   # 4:5 portrait
        y = int(H * 0.58)
    else:                 # 1:1 square
        y = int(H * 0.55)

    # ── Niche line — hero text on the image ───────────────────────────────────
    if niche_line:
        n_max_size = int(H * 0.105)
        n_min_size = int(H * 0.050)
        n_font, n_lines = _fit_headline_font(
            draw, niche_line, text_max_w, n_max_size, n_min_size,
            "Montserrat-ExtraBoldItalic.ttf",
        )
        n_stroke = max(3, n_font.size // 14)
        n_line_h = int(n_font.size * 1.15)
        for line in n_lines:
            draw.text(
                (LEFT, y), line, font=n_font, fill=_WHITE,
                stroke_width=n_stroke, stroke_fill=_BLACK_STROKE,
            )
            y += n_line_h
        y += gap_after_niche

    # ── Offer line ────────────────────────────────────────────────────────────
    if offer_line:
        o_size = min(int(H * 0.066), int(W * 0.075))
        o_font = _load_font("Montserrat-Bold.ttf", o_size)
        o_stroke = max(3, o_size // 18)
        o_lines = _wrap_to_width(draw, offer_line, o_font, text_max_w)
        o_line_h = int(o_font.size * 1.15)
        for o_line in o_lines:
            draw.text(
                (LEFT, y), o_line, font=o_font, fill=_WHITE,
                stroke_width=o_stroke, stroke_fill=_BLACK_STROKE,
            )
            y += o_line_h

    # ── Logo badge (top-right) ─────────────────────────────────────────────────
    if logo_url:
        try:
            resp = requests.get(logo_url, timeout=10)
            resp.raise_for_status()
            logo_img = Image.open(io.BytesIO(resp.content)).convert("RGBA")

            max_logo_w = int(W * 0.30)
            max_logo_h = int(H * 0.12)
            logo_img.thumbnail((max_logo_w, max_logo_h), Image.LANCZOS)
            lw, lh = logo_img.size

            pad = int(W * 0.013)
            badge_w = lw + 2 * pad
            badge_h = lh + 2 * pad
            badge_x = W - badge_w - int(W * 0.03)
            badge_y = int(H * 0.025)

            badge_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            badge_draw = ImageDraw.Draw(badge_layer)
            badge_draw.rounded_rectangle(
                [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
                radius=int(badge_h * 0.28),
                fill=(255, 255, 255, 242),
            )
            badge_layer.paste(logo_img, (badge_x + pad, badge_y + pad), logo_img)
            overlay = Image.alpha_composite(overlay, badge_layer)

        except Exception as exc:
            logger.warning("Logo overlay skipped: %s", exc)

    # ── Composite & return ────────────────────────────────────────────────────
    result = Image.alpha_composite(img, overlay).convert("RGB")
    out = io.BytesIO()
    result.save(out, format="PNG", optimize=True)
    return out.getvalue()
