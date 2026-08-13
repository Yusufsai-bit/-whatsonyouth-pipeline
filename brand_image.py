"""
What's On Youth — Locked Production Branding

Assets used exactly as provided. No redesign. No improvisation.

Output spec:
  1080 x 1350 px total
  1080 x 1230 px flyer area  (top)
  1080 x  120 px footer area (bottom)
  80   x   80 px icon at (28, 28) — top-left of canvas, behind event photo
"""

import io
import requests
from PIL import Image, ImageFilter
from pathlib import Path

# ── Locked asset paths ─────────────────────────────────────────────────────────
ASSET_DIR = Path(__file__).parent / "assets"

FOOTERS = {
    "light": ASSET_DIR / "WOY_footer_light_1080x120_centered.png",
    "dark":  ASSET_DIR / "WOY_footer_dark_1080x120_centered.png",
    "teal":  ASSET_DIR / "WOY_footer_teal_1080x120_centered.png",
}
ICON_PATH = ASSET_DIR / "WOY_top_left_true_icon_72x72.png"

# ── Locked output dimensions ───────────────────────────────────────────────────
CANVAS_W = 1080
CANVAS_H = 1350
FLYER_H  = 1230
FOOTER_H = 120
ICON_PAD      = 28          # 28 px from top and left edges
ICON_DISPLAY  = 80          # ~7.4% of 1080px canvas width

# ── Template keyword detection ─────────────────────────────────────────────────
_DARK_KW = {"job","career","leadership","grant","network","professional",
             "finance","management","business","blueprint","risk","speaking",
             "stem","changemaker","gamification","girls in business"}
_TEAL_KW = {"wellbeing","mental health","support","community","festival",
             "clothes swap","social","autistic","meet-up","meetup","poetry",
             "theatre","environment","chinese youth","friday youth","ya yap",
             "textile","autism"}

def detect_template(title: str) -> str:
    t = title.lower()
    if any(k in t for k in _DARK_KW): return "dark"
    if any(k in t for k in _TEAL_KW): return "teal"
    return "light"


def brand_image(
    image_url: str,
    out_path:  str,
    title:     str = "",
    template:  str | None = None,
    local_path: str | None = None,
) -> Image.Image:

    if template is None:
        template = detect_template(title)

    # ── Load flyer ─────────────────────────────────────────────────────────────
    if local_path:
        flyer = Image.open(local_path).convert("RGBA")
    else:
        resp = requests.get(image_url, timeout=20)
        resp.raise_for_status()
        flyer = Image.open(io.BytesIO(resp.content)).convert("RGBA")
    fw, fh = flyer.size

    # ── Blurred background — cover-fill 1080×1230, no black bars ──────────────
    # Scale to COVER (fill every pixel), then center-crop to 1080×1230
    scale_cover = max(CANVAS_W / fw, FLYER_H / fh)
    bg_w = int(fw * scale_cover)
    bg_h = int(fh * scale_cover)
    bg = flyer.resize((bg_w, bg_h), Image.LANCZOS)
    crop_x = (bg_w - CANVAS_W) // 2
    crop_y = (bg_h - FLYER_H)  // 2
    bg_cropped  = bg.crop((crop_x, crop_y, crop_x + CANVAS_W, crop_y + FLYER_H))
    # Softer blur + slight dim so background recedes behind the sharp flyer
    bg_blurred  = bg_cropped.filter(ImageFilter.GaussianBlur(radius=38))
    bg_dimmed   = bg_blurred.point(lambda p: int(p * 0.80))

    # ── Canvas: blurred flyer as background ────────────────────────────────────
    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 255))
    canvas.alpha_composite(bg_dimmed.convert("RGBA"), dest=(0, 0))

    # ── Icon: placed on blurred background BEFORE the sharp flyer so it never
    #    sits on top of the event photo — top-left corner with consistent padding
    icon_src = Image.open(ICON_PATH).convert("RGBA")
    icon     = icon_src.resize((ICON_DISPLAY, ICON_DISPLAY), Image.LANCZOS)
    canvas.alpha_composite(icon, dest=(ICON_PAD, ICON_PAD))

    # ── Sharp flyer — fit inside 1080×1230, centred on blurred background ──────
    scale_fit = min(CANVAS_W / fw, FLYER_H / fh)
    new_w = int(fw * scale_fit)
    new_h = int(fh * scale_fit)
    flyer_scaled = flyer.resize((new_w, new_h), Image.LANCZOS)

    paste_x = (CANVAS_W - new_w) // 2
    paste_y = (FLYER_H  - new_h) // 2
    canvas.alpha_composite(flyer_scaled, dest=(paste_x, paste_y))

    # ── Footer: locked 1080×120 asset flush to bottom ─────────────────────────
    footer = Image.open(FOOTERS[template]).convert("RGBA")
    canvas.alpha_composite(footer, dest=(0, FLYER_H))

    # ── Export ─────────────────────────────────────────────────────────────────
    result = canvas.convert("RGB")
    result.save(out_path, format="JPEG", quality=95, optimize=True)
    kb = Path(out_path).stat().st_size // 1024
    print(f"  [{template.upper():5}] {CANVAS_W}x{CANVAS_H}px  ({kb} KB)  ->  {out_path}")
    return result


if __name__ == "__main__":
    TEST_URL = (
        "https://img.evbuc.com/https%3A%2F%2Fcdn.evbuc.com%2Fimages%2F"
        "1180979952%2F225618608799%2F1%2Foriginal.20260330-102030"
        "?crop=focalpoint&fit=crop&w=640&auto=format%2Ccompress&q=75"
        "&sharp=10&fp-x=0.534&fp-y=0.097&s=e0e91b527925abc66d6676f2133404fc"
    )
    TITLE = "WORKS IN PROGRESS - A Pathway to Your Future - Youth Summit 2026"
    OUT   = r"C:\Users\yusuf\Downloads"

    # One preview only — wait for approval before processing all 20 events
    brand_image(TEST_URL, rf"{OUT}\branded_preview.jpg", TITLE)
    print("\nSingle preview generated. Review before batch.")
