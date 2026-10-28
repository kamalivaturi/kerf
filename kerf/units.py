"""Timeline intake: each editor's framing units <-> Kerf units, both directions, in one module.

Kerf units: base_scale is % of the clip's native pixels; base_center is the offset from frame centre in frame
fractions (y down). Adapters send what their editor reports (raw), with the editor's id; nothing else converts.

  premiere  scale: % of native pixels; position: pixels or 0..1 of the frame (UXP reports either), y down
  resolve   zoom: x over fit-to-frame; pan / tilt: pixels from centre, tilt up
"""
from __future__ import annotations


def framing_in(editor, raw, frame, source):
    """(base_scale, base_center) from the editor's raw reading of one clip."""
    W, H = frame
    if editor == "premiere":
        x, y = (float(v) for v in raw["position"])
        if abs(x) > 2 or abs(y) > 2:  # pixels; otherwise already 0..1
            x, y = x / W, y / H
        return float(raw.get("scale") or 100.0), (x - 0.5, y - 0.5)
    if editor == "resolve":
        sw, sh = source
        return float(raw["zoom"]) * min(W / sw, H / sh) * 100, (float(raw["pan"]) / W, -float(raw["tilt"]) / H)
    raise ValueError(f"unknown editor '{editor}'")


def framing_out(editor, base_scale, base_center, frame, source):
    """The editor's raw reading for Kerf framing: the inverse of framing_in (positions in pixels)."""
    W, H = frame
    bx, by = base_center
    if editor == "premiere":
        return dict(scale=base_scale, position=[(bx + 0.5) * W, (by + 0.5) * H])
    if editor == "resolve":
        sw, sh = source
        return dict(zoom=base_scale / 100 / min(W / sw, H / sh), pan=bx * W, tilt=-by * H)
    raise ValueError(f"unknown editor '{editor}'")


def xml_motion(editor, frame, source):
    """How a Basic Motion value in that editor's XML import reads Kerf units: (scale divisor, centre x, centre y).

    XML scale = scale% * base_scale / divisor; XML centre = (offset + base_center) * (kx, ky)."""
    W, H = frame
    sw, sh = source
    if editor == "resolve":  # scale over fit-to-frame, centre in frame fractions
        return min(W / sw, H / sh), 1.0, 1.0
    return 1.0, W / sw, H / sh  # Premiere: scale over native pixels, centre in source fractions


def clip_framing(c, editor, frame, source_of):
    """base_scale / base_center for a clip dict: from its raw editor framing when present, else as given."""
    raw = c.get("framing")
    if raw and editor:
        return framing_in(editor, raw, frame, raw.get("source") or source_of(c["path"]))
    return float(c.get("base_scale") or 100.0), tuple(float(v) for v in (c.get("base_center") or (0.0, 0.0)))
