"""Extract embedded images from example_exams ODTs into few_shot/images/<範例編號>/.

Run once (idempotent):
    uv run python scripts/extract_few_shot_images.py

Each ODT is a zip archive.  We parse content.xml in document order to collect
<draw:image xlink:href="Pictures/..."> nodes, copy the referenced bytes into
data/social_studies/few_shot/images/<範例編號>/figure{N}.{ext}, and write a
manifest.json listing file + best-effort caption text.
"""

from __future__ import annotations

import json
import shutil
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_DIR = REPO_ROOT / "data" / "social_studies" / "example_exams"
OUTPUT_DIR = REPO_ROOT / "data" / "social_studies" / "few_shot" / "images"

# Mapping retired in #542 (PISA-reading corpus removal).
# ex001–ex006 entries are intentionally removed so re-running this script
# cannot silently regenerate the deleted corpus images.
# When #544 adds ICCS-native ODTs, add their entries here.
ODT_TO_EXAMPLE: dict[str, str] = {}

_NS = {
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
}

_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"


def _iter_text_and_images(root: ET.Element) -> list[tuple[str, str | None]]:
    """Walk content.xml depth-first, yield (kind, value) pairs in order.

    kind='text' → surrounding paragraph text (stripped)
    kind='image' → Pictures/... href
    """
    events: list[tuple[str, str | None]] = []
    body = root.find("office:body", _NS)
    if body is None:
        body = root

    def _walk(el: ET.Element) -> None:
        tag_local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        ns_uri = el.tag.split("}")[0].lstrip("{") if "}" in el.tag else ""

        if ns_uri == _NS["text"] and tag_local == "p":
            text = "".join(el.itertext()).strip()
            if text:
                events.append(("text", text))

        if ns_uri == _NS["draw"] and tag_local == "image":
            href = el.get(_XLINK_HREF, "")
            if href.startswith("Pictures/"):
                events.append(("image", href))

        for child in el:
            _walk(child)

    _walk(body)
    return events


def extract_odt(odt_path: Path, example_id: str) -> None:
    out_dir = OUTPUT_DIR / example_id
    out_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(odt_path) as zf:
        xml_bytes = zf.read("content.xml")
        root = ET.fromstring(xml_bytes)
        events = _iter_text_and_images(root)

        manifest: list[dict] = []
        img_idx = 0
        last_text: str = ""

        for kind, value in events:
            if kind == "text":
                last_text = value or ""
            elif kind == "image" and value:
                img_idx += 1
                src = value  # e.g. "Pictures/abc.jpg"
                ext = Path(src).suffix.lower() or ".png"
                dest_name = f"figure{img_idx}{ext}"
                dest = out_dir / dest_name
                raw = zf.read(src)
                dest.write_bytes(raw)
                manifest.append({"file": dest_name, "caption": last_text})
                last_text = ""

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  {example_id}: {img_idx} images → {out_dir}")


def main() -> None:
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    for odt_name, example_id in ODT_TO_EXAMPLE.items():
        odt_path = EXAMPLE_DIR / odt_name
        if not odt_path.exists():
            print(f"  SKIP {odt_name} (not found)")
            continue
        extract_odt(odt_path, example_id)

    print("Done.")


if __name__ == "__main__":
    main()
