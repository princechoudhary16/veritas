"""C2PA embed -> read round-trip (skipped if optional deps are absent)."""

import pytest

pytest.importorskip("c2pa")
pytest.importorskip("cryptography")
Image = pytest.importorskip("PIL.Image")


def test_embed_and_read_roundtrip(tmp_path):
    from veritas.c2pa_export import embed_receipt, read_credential

    src = tmp_path / "src.webp"
    Image.new("RGB", (64, 64), (40, 160, 120)).save(str(src), format="WEBP")
    out = tmp_path / "signed.webp"
    receipt = {
        "policy": "demo", "passed": True,
        "verification": {"final_scores": {"grounding": {"pass": True, "score": 1.0}}},
        "assets": {"image_sha256": "deadbeef"},
    }

    embed_receipt(str(src), receipt, str(out))
    data = read_credential(str(out))

    labels = [a.get("label")
              for m in data.get("manifests", {}).values()
              for a in m.get("assertions", [])]
    assert any("veritas" in (label or "") for label in labels)
    assert data.get("validation_state") == "Valid"
