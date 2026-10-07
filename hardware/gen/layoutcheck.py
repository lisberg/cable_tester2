"""Readability check for generated sheets: overlapping text, text on wires/bodies, wires through bodies.

Works on the in-memory Sheet model (before writing). Text extents are estimated for the KiCad stroke
font (character advance ≈ 0.8 × size), which is close enough to catch real collisions.
"""
from schgen import Sym

CHAR = 0.8          # advance per character, × font size
SIZE = 1.27
EPS = 0.25          # tolerance: touching is fine


def _text_box(text, x, y, justify, size=SIZE, angle=0):
    w, h = len(text) * CHAR * size, size * 1.3          # glyph height incl. stroke and inter-line gap
    j = (justify or "").split()
    if angle in (90, 270):
        # vertical text: width along y
        if "left" in j:
            y0, y1 = (y - w, y) if angle == 90 else (y, y + w)
        elif "right" in j:
            y0, y1 = (y, y + w) if angle == 90 else (y - w, y)
        else:
            y0, y1 = y - w / 2, y + w / 2
        x0, x1 = (x - h, x) if "bottom" in j else (x - h / 2, x + h / 2)
        return x0, y0, x1, y1
    if "left" in j:
        x0, x1 = x, x + w
    elif "right" in j:
        x0, x1 = x - w, x
    else:
        x0, x1 = x - w / 2, x + w / 2
    if "bottom" in j:
        y0, y1 = y - h, y
    elif "top" in j:
        y0, y1 = y, y + h
    else:
        y0, y1 = y - h / 2, y + h / 2
    return x0, y0, x1, y1


def _overlap(a, b, eps=EPS):
    return a[0] < b[2] - eps and b[0] < a[2] - eps and a[1] < b[3] - eps and b[1] < a[3] - eps


def _seg_hits_box(seg, box, eps=EPS):
    x1, y1, x2, y2 = (round(v, 2) for v in seg)
    bx0, by0, bx1, by1 = box[0] + eps, box[1] + eps, box[2] - eps, box[3] - eps
    if bx0 >= bx1 or by0 >= by1:
        return False
    if y1 == y2:
        return by0 < y1 < by1 and min(x1, x2) < bx1 and max(x1, x2) > bx0
    if x1 == x2:
        return bx0 < x1 < bx1 and min(y1, y2) < by1 and max(y1, y2) > by0
    return False


def boxes(sheet, ref_len=5):
    """Collect (kind, name, box) for texts, bodies, labels."""
    out = []
    for s in sheet.syms:
        x0, y0, x1, y1, _ = s.bbox()
        if s.dnp:                              # DNP cross extends beyond the body
            x0, y0, x1, y1 = x0 - 1.27, y0 - 1.27, x1 + 1.27, y1 + 1.27
        name = f"{s.prefix}{s.idx}"
        if not s.lib.is_power:
            out.append(("body", name, (x0, y0, x1, y1)))
        (rx, ry, rj), (vx, vy, vj) = s._text_spots()
        if not s.lib.is_power:
            out.append(("ref", name, _text_box("X" * ref_len, rx, ry, rj)))
        if s.value:
            out.append(("value", f"{name}:{s.value}", _text_box(s.value, vx, vy, vj)))
        if s.lib.is_power:
            out.append(("body", name, (x0, y0, x1, y1)))
    for it in sheet.items:
        if it[0] in ("label", "global_label", "hierarchical_label"):
            name = it[1]
            at = [e for e in it if isinstance(e, list) and e[0] == "at"][0]
            x, y, a = float(at[1]), float(at[2]), int(at[3])
            n = len(name) + (2 if it[0] != "label" else 0)          # shape outline for hier/global
            w, h = n * CHAR * SIZE, SIZE * 1.3
            lift = 0.25 if it[0] == "label" else 0
            hh = 1.0                                                # half height of hier/global label outline
            if a == 0:
                box = (x, y - h - lift, x + w, y - lift) if it[0] == "label" else (x, y - hh, x + w, y + hh)
            elif a == 180:
                box = (x - w, y - h - lift, x, y - lift) if it[0] == "label" else (x - w, y - hh, x, y + hh)
            elif a == 90:
                box = (x - h - lift, y - w, x - lift, y) if it[0] == "label" else (x - hh, y - w, x + hh, y)
            else:
                box = (x - h - lift, y, x - lift, y + w) if it[0] == "label" else (x - hh, y, x + hh, y + w)
            out.append(("label", name, box))
        elif it[0] == "text":
            at = [e for e in it if isinstance(e, list) and e[0] == "at"][0]
            lines = it[1].split("\n")
            w = max(len(l) for l in lines) * CHAR * SIZE
            out.append(("note", it[1][:20], (float(at[1]), float(at[2]), float(at[1]) + w,
                                             float(at[2]) + len(lines) * SIZE * 1.6)))
    for sh in sheet.sheets:
        out.append(("body", sh.name, (sh.x, sh.y, sh.x + sh.w, sh.y + sh.h)))
        for pname, (x, y, a, _) in sh.pins.items():
            w = len(pname) * CHAR * SIZE
            box = (x + 1.0, y - SIZE / 2, x + 1.0 + w, y + SIZE / 2) if a == 180 else \
                  (x - 1.0 - w, y - SIZE / 2, x - 1.0, y + SIZE / 2)
            out.append(("sheetpin", f"{sh.name}.{pname}", box))
    return out


def check(sheet):
    items = boxes(sheet)
    issues = []
    texts = [b for b in items if b[0] in ("ref", "value", "label", "note")]
    bodies = [b for b in items if b[0] == "body"]
    # text vs text
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            if _overlap(a[2], b[2]):
                issues.append(f"text/text: {a[0]} {a[1]!r} × {b[0]} {b[1]!r}")
    # text vs bodies
    for t in texts:
        for b in bodies:
            if t[0] in ("ref", "value") and t[1].split(":")[0] == b[1]:
                continue
            if _overlap(t[2], b[2]):
                issues.append(f"text/body: {t[0]} {t[1]!r} × {b[1]}")
    # text vs wires and vs drawn pin lines (labels sit on their own wire end: skip segments touching the anchor)
    pin_lines = [(f"{sym.prefix}{sym.idx}", seg) for sym in sheet.syms for seg in sym.pin_segments()]
    for t in texts:
        for seg in sheet.segs:
            if _seg_hits_box(seg, t[2]):
                issues.append(f"text/wire: {t[0]} {t[1]!r} × wire {seg}")
        for owner, seg in pin_lines:
            if _seg_hits_box(seg, t[2]):
                issues.append(f"text/pin: {t[0]} {t[1]!r} × pin line of {owner} {seg}")
    # wires through bodies (pins end on the body edge, so shrink the box); a wire that starts on one of
    # the symbol's own pins leaves outward by construction and is not a crossing
    own_pins = {}
    for sym in sheet.syms:
        own_pins.setdefault(f"{sym.prefix}{sym.idx}", set()).update(
            (x, y) for x, y, _ in (sym.pin(p.number, mark=False) for p in sym.all_pins()))
    for b in bodies:
        pins = own_pins.get(b[1], set())
        for seg in sheet.segs:
            if (seg[0], seg[1]) in pins or (seg[2], seg[3]) in pins:
                continue
            if _seg_hits_box(seg, b[2], eps=0.6):
                issues.append(f"wire/body: {b[1]} × wire {seg}")
    # every connected pin leaves through its own short wire: no pin directly on another pin, on a power
    # symbol, or on the middle of a wire (house style)
    ends, segs = {}, sheet.segs
    for x1, y1, x2, y2 in segs:
        for pt in ((x1, y1), (x2, y2)):
            ends[pt] = ends.get(pt, 0) + 1
    ncs = {(float(e[1]), float(e[2])) for it in sheet.items if it[0] == "no_connect"
           for e in it if isinstance(e, list) and e[0] == "at"}
    owner = {}
    for sym in sheet.syms:
        for p in sym.all_pins():
            if p.hidden:
                continue
            pt = sym.pin(p.number, mark=False)[:2]
            owner.setdefault(pt, set()).add(f"{sym.prefix}{sym.idx}")
    for sym in sheet.syms:
        name = f"{sym.prefix}{sym.idx}"
        for p in sym.all_pins():
            if p.hidden or p.etype == "no_connect":
                continue
            pt = sym.pin(p.number, mark=False)[:2]
            if pt in ncs:
                continue
            others = owner.get(pt, set()) - {name}
            if others:
                issues.append(f"pin/pin: {name}.{p.number} sits directly on {sorted(others)}")
            elif not ends.get(pt):
                inside = any((x1 == x2 == pt[0] and min(y1, y2) < pt[1] < max(y1, y2)) or
                             (y1 == y2 == pt[1] and min(x1, x2) < pt[0] < max(x1, x2)) for x1, y1, x2, y2 in segs)
                issues.append(f"pin/{'wire' if inside else 'none'}: {name}.{p.number} has no own wire"
                              + (" (sits on a wire)" if inside else ""))
    # body vs body
    for i, a in enumerate(bodies):
        for b in bodies[i + 1:]:
            if _overlap(a[2], b[2], eps=0.1):
                issues.append(f"body/body: {a[1]} × {b[1]}")
    return issues
