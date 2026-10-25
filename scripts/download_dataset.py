"""Retrieve version 2 from Kaggle and verify all nine files before copying them."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Use an existing original dataset directory instead of downloading")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "docs/raw_dataset_manifest.json").read_text())
    if args.source is None:
        import kagglehub
        source = Path(kagglehub.dataset_download(manifest["handle"]))
    else:
        source = args.source.resolve()
    for item in manifest["files"]:
        path = source / item["file"]
        if path.stat().st_size != item["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"The original version-2 file differs from its manifest: {item['file']}")
    destination = ROOT / "data/raw/olist-v2"
    destination.mkdir(parents=True, exist_ok=True)
    for item in manifest["files"]:
        if (source / item["file"]).resolve() != (destination / item["file"]).resolve():
            shutil.copy2(source / item["file"], destination / item["file"])
    print(f"Verified and prepared {len(manifest['files'])} original version-2 files. No cloud resources were contacted.")


if __name__ == "__main__":
    main()
