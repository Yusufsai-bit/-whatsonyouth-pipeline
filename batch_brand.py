"""Brand all 20 events and save a manifest for Blotato upload."""
import csv, json, sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\yusuf")
from brand_image import brand_image

OUT_DIR = Path(r"C:\Users\yusuf\branded_posts")
OUT_DIR.mkdir(exist_ok=True)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def make_caption(e: dict) -> str:
    parts = [f"\U0001f389 {e['title']}"]
    if e['date']:     parts.append(f"\U0001f4c5 {e['date']}")
    if e['location']: parts.append(f"\U0001f4cd {e['location']}")
    parts.append(f"\U0001f39f️ Grab your spot: {e['url']}")
    return "\n\n".join(parts) + "\n\n#WhatsOnYouth #MelbourneYouth #YouthEvents #Melbourne"

results = []
with open(r"C:\Users\yusuf\melbourne_youth_events.csv", newline="", encoding="utf-8") as f:
    for i, row in enumerate(csv.DictReader(f), 1):
        title     = row["title"]
        image_url = row["image_url"].strip()
        out_path  = str(OUT_DIR / f"event_{i:02d}.jpg")

        if not image_url:
            print(f"  [{i:02d}] SKIP — no image: {title[:55]}")
            continue

        try:
            brand_image(image_url, out_path, title)
            results.append({
                "num":        i,
                "title":      title,
                "caption":    make_caption(row),
                "url":        row["url"],
                "image_path": out_path,
            })
        except Exception as exc:
            print(f"  [{i:02d}] ERROR — {exc} — {title[:55]}")

print(f"\n{len(results)}/20 branded successfully.")

with open(str(OUT_DIR / "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print("Manifest written to branded_posts/manifest.json")
