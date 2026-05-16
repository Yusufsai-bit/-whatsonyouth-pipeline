"""Upload a single branded image to a Blotato presigned URL via HTTP PUT."""
import sys
import requests


def upload(image_path: str, presigned_url: str) -> bool:
    with open(image_path, "rb") as f:
        data = f.read()
    resp = requests.put(presigned_url, data=data)
    if resp.status_code == 200:
        print(f"OK  {image_path}")
        return True
    print(f"FAIL {resp.status_code}: {resp.text[:200]}")
    return False


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python woy_upload.py <image_path> <presigned_url>")
        sys.exit(1)
    ok = upload(sys.argv[1], sys.argv[2])
    sys.exit(0 if ok else 1)
