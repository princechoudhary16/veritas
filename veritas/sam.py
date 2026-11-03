"""Parse SAM 3.1 segmentation output into usable detections.

SAM 3.1 (via the Responses API) returns special-token text, one box + one mask
per matched instance, e.g.:

    <|box;x1=615;y1=104;x2=984;y2=1501;w=1600;h=1600|><|mask;...|>

We only need the boxes for grounding: how many instances, and how much of the
frame each occupies (prominence). Masks are ignored for now.
"""

from __future__ import annotations

import re

_BOX_RE = re.compile(
    r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)\|>"
)


def parse_sam_output(text: str) -> dict:
    detections: list[dict] = []
    img_w = img_h = 0
    for m in _BOX_RE.finditer(text or ""):
        x1, y1, x2, y2, w, h = map(int, m.groups())
        img_w, img_h = w, h
        area = max(0, x2 - x1) * max(0, y2 - y1)
        frac = area / (w * h) if w and h else 0.0
        detections.append(
            {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "area_frac": round(frac, 4)}
        )
    return {
        "image": {"w": img_w, "h": img_h},
        "detections": detections,
        "count": len(detections),
    }
