"""
What's On Youth — Blotato Publish via REST API
Reads manifest.json, uploads each branded image, schedules IG + FB posts.

Run after woy_pipeline.py:
  python woy_publish_api.py
"""
import json, os, sys, time
from pathlib import Path
import requests

API_KEY = os.environ.get("BLOTATO_API_KEY")
if not API_KEY:
    sys.exit("Error: BLOTATO_API_KEY environment variable not set.")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "https://backend.blotato.com"

IG_ACCOUNT_ID = "43819"
FB_ACCOUNT_ID = "29099"
FB_PAGE_ID    = "1035821056287360"

MANIFEST_PATH = Path(__file__).parent / "branded_posts" / "manifest.json"

HEADERS = {
    "Content-Type": "application/json",
    "blotato-api-key": API_KEY,
}


def get_presigned_url(filename: str) -> tuple[str, str]:
    """Return (presignedUrl, publicUrl) for a fresh upload slot."""
    resp = requests.post(
        f"{BASE_URL}/v2/media/uploads",
        headers=HEADERS,
        json={"filename": filename},
        timeout=20,
    )
    resp.raise_for_status()
    d = resp.json()
    return d["presignedUrl"], d["publicUrl"]


def upload_image(image_path: str, presigned_url: str) -> None:
    """PUT raw binary to presigned URL — no Content-Type header."""
    with open(image_path, "rb") as f:
        data = f.read()
    resp = requests.put(presigned_url, data=data, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Upload failed {resp.status_code}: {resp.text[:200]}")


def create_post(account_id: str, platform: str, text: str,
                media_urls: list, scheduled_time: str,
                page_id: str = None) -> str:
    """Schedule a post. Returns postSubmissionId."""
    target = {"targetType": platform}
    if page_id:
        target["pageId"] = page_id

    payload = {
        "post": {
            "accountId": account_id,
            "content": {
                "text": text,
                "mediaUrls": media_urls,
                "platform": platform,
            },
            "target": target,
        },
        "scheduledTime": scheduled_time,
    }
    resp = requests.post(
        f"{BASE_URL}/v2/posts",
        headers=HEADERS,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("postSubmissionId", "unknown")


def run():
    if not MANIFEST_PATH.exists():
        sys.exit("manifest.json not found — run woy_pipeline.py first.")

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)

    if not manifest:
        print("  No events in manifest — nothing to publish.")
        return

    schedulable = [e for e in manifest if e.get("scheduled_time")]
    skipped     = len(manifest) - len(schedulable)

    print(f"\n{'='*60}")
    print(f"  What's On Youth — Blotato Publish")
    print(f"  {len(schedulable)} to post  |  {skipped} skipped (past threshold)")
    print(f"{'='*60}\n")

    ok_count = 0
    for e in schedulable:
        title = e["title"][:45]
        path  = e["image_path"]
        print(f"  [{e['num']:02d}] {title}")
        try:
            presigned_url, public_url = get_presigned_url(Path(path).name)
            upload_image(path, presigned_url)

            create_post(IG_ACCOUNT_ID, "instagram",
                        e["caption"], [public_url], e["scheduled_time"])
            create_post(FB_ACCOUNT_ID, "facebook",
                        e["caption"], [public_url], e["scheduled_time"],
                        page_id=FB_PAGE_ID)

            print(f"        IG + FB scheduled  ->  {e['scheduled_time']}")
            ok_count += 1
        except Exception as exc:
            print(f"        ERROR: {exc}")

        time.sleep(2)  # stay within 30 req/min on post endpoint

    print(f"\n  Published: {ok_count}/{len(schedulable)}  |  Skipped: {skipped}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    run()
