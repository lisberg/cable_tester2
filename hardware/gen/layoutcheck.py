"""Readability check for generated sheets: overlapping text, text on wires/bodies, wires through bodies.

Works on the in-memory Sheet model (before writing). Text extents are estimated for the KiCad stroke
font (character advance ≈ 0.8 × size), which is close enough to catch real collisions.
"""
from schgen import Sym

CHAR = 1.0          # advance per character, × font size (KiCad 10 PDF: 1.15-1.33 mm per character at 1.27)
SIZE = 1.27
EPS = 0.25          # tolerance: touching is fine
CLEAR = 0.75        # minimum gap between text and a wire it does not belong to (reads as touching below this)
TEXT_GAP = 0.5      # minimum gap between two texts
TITLE_MAX = 66      # title-block title field: ~1.45 mm per character, ~107 mm wide incl. "Title: "


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
        h = SIZE * 1.3
        out.append(("sheettext", sh.name, (sh.x, sh.y - 0.7 - h, sh.x + len(sh.name) * CHAR * SIZE, sh.y - 0.7)))
        fn = f"File: {sh.child.filename}"
        out.append(("sheettext", fn, (sh.x, sh.y + sh.h + 0.7, sh.x + len(fn) * CHAR * SIZE, sh.y + sh.h + 0.7 + h)))
        for pname, (x, y, a, _) in sh.pins.items():
            w = len(pname) * CHAR * SIZE
            box = (x + 1.0, y - SIZE / 2, x + 1.0 + w, y + SIZE / 2) if a == 180 else \
                  (x - 1.0 - w, y - SIZE / 2, x - 1.0, y + SIZE / 2)
            out.append(("sheetpin", f"{sh.name}.{pname}", box))
    return out


def _gap(box, seg):
    """Distance between an axis-aligned box and a horizontal/vertical segment (0 if they touch)."""
    x1, y1, x2, y2 = seg
    dx = max(box[0] - max(x1, x2), min(x1, x2) - box[2], 0)
    dy = max(box[1] - max(y1, y2), min(y1, y2) - box[3], 0)
    return (dx * dx + dy * dy) ** 0.5


def _visible_texts(sheet):
    out = [("title", sheet.title)]
    for s in sheet.syms:
        if s.value:
            out.append((f"{s.prefix}{s.idx} value", s.value))
    for it in sheet.items:
        if it[0] in ("label", "global_label", "hierarchical_label", "text"):
            out.append((it[0], it[1]))
    for sh in sheet.sheets:
        out += [("sheet", sh.name)] + [("sheet pin", p) for p in sh.pins]
    return out


def check(sheet):
    items = boxes(sheet)
    issues = []
    # visible text is ASCII-only: the KiCad stroke font has no arrows, dashes, Ohm, <= ...
    for what, t in _visible_texts(sheet):
        if any(ord(ch) > 126 for ch in t):
            issues.append(f"non-ASCII: {what} {t!r}")
    if len(sheet.title) > TITLE_MAX:
        issues.append(f"title: {len(sheet.title)} characters overflow the title block (max {TITLE_MAX})")
    texts = [b for b in items if b[0] in ("ref", "value", "label", "note", "sheettext")]
    bodies = [b for b in items if b[0] == "body"]
    # text vs text
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            if _overlap(a[2], b[2], eps=-TEXT_GAP):          # neighbouring texts must not run together
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
    # text running along a wire it does not belong to, too close to read as separate (e.g. a label under a
    # wire that continues over it one row up, a GND symbol's text against the next row's wire). Wires that
    # touch the text's own anchor / symbol pins are skipped, and so is mere corner proximity: the wire must
    # run alongside the text for at least 1 mm.
    def rp(x, y):
        return round(x, 2), round(y, 2)

    anchors = {}
    for sym in sheet.syms:
        anchors[f"{sym.prefix}{sym.idx}"] = {rp(*sym.pin(p.number, mark=False)[:2]) for p in sym.all_pins()}
    for it in sheet.items:
        if it[0] in ("label", "global_label", "hierarchical_label"):
            at = [e for e in it if isinstance(e, list) and e[0] == "at"][0]
            anchors.setdefault(it[1], set()).add(rp(float(at[1]), float(at[2])))
    for t in texts:
        if t[0] in ("note", "sheettext"):
            continue
        own = anchors.get(t[1].split(":")[0], set())
        box = t[2]
        for seg in sheet.segs:
            a, b = rp(seg[0], seg[1]), rp(seg[2], seg[3])
            if a in own or b in own:
                continue
            if any((a[0] == x == b[0] and min(a[1], b[1]) <= y <= max(a[1], b[1])) or
                   (a[1] == y == b[1] and min(a[0], b[0]) <= x <= max(a[0], b[0])) for x, y in own):
                continue                                    # the wire runs through the anchor (label mid-wire)
            if a[1] == b[1]:
                along = min(max(a[0], b[0]), box[2]) - max(min(a[0], b[0]), box[0])
            else:
                along = min(max(a[1], b[1]), box[3]) - max(min(a[1], b[1]), box[1])
            if along >= 1.0 and _gap(box, seg) < CLEAR and not _seg_hits_box(seg, box):
                issues.append(f"text/wire clearance: {t[0]} {t[1]!r} {_gap(box, seg):.2f} mm from wire {seg}")
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
                if ends.get(pt) or owner.get(pt, set()) - {name}:
                    issues.append(f"pin/nc: {name}.{p.number} has a no-connect flag but is wired")
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
