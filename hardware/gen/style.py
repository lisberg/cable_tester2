"""House-style building blocks for generated schematics (see .claude/skills/ecad-house-style/SKILL.md).

Every helper obeys the drawing rules enforced by layoutcheck.py:
  * every pin leaves through its own short wire (no part directly on a wire, pin or power symbol),
  * parts tap a line with a stub + junction dot, power symbols sit at the end of a stub,
  * text is placed beside the body, never on pins or wires.
New designs import from here instead of re-implementing placement.
"""
from schgen import Sheet  # noqa: F401  (re-exported for convenience)

U = 2.54

# ------------------------------------------------------------------------------------------- footprints / helpers
FP_R0603 = "Resistor_SMD:R_0603_1608Metric"
FP_R1206 = "Resistor_SMD:R_1206_3216Metric"
FP_C0603 = "Capacitor_SMD:C_0603_1608Metric"
FP_C0805 = "Capacitor_SMD:C_0805_2012Metric"
FP_TSSOP16 = "Package_SO:TSSOP-16_4.4x5mm_P0.65mm"
FP_TSSOP14 = "Package_SO:TSSOP-14_4.4x5mm_P0.65mm"
FP_SOT235 = "Package_TO_SOT_SMD:SOT-23-5"
FP_TP = "TestPoint:TestPoint_Pad_D1.0mm"
TI = {"Manufacturer": "Texas Instruments"}


def R(s, at, value, rot=0, fp=FP_R0603, **kw):
    return s.add("Device:R", "R", at, rot=rot, value=value, footprint=fp, **kw)


def C(s, at, value="100n", rot=0, fp=FP_C0603, **kw):
    return s.add("Device:C", "C", at, rot=rot, value=value, footprint=fp, **kw)


def hier(s, obj, pin, net, shape="passive", stub=5.08):
    s.connect(obj, pin, net, kind="hier", shape=shape, stub=stub)


def decap(s, ic, pin="VCC", rail="VDD5", values=("100n",), dx=None, up=None, side=1):
    """Rail symbol above the power pin, caps hanging off a horizontal wire beside the body, to GND."""
    x, y = ic.pos(pin)
    x0, y0, x1, y1, _ = ic.bbox()
    if up is None:                      # cap + GND symbol + text must clear the body top
        up = max(7.62, round((y - y0 + 17.78) / U) * U)
    if dx is None:
        edge = (x1 - x) if side > 0 else (x - x0)
        dx = side * max(7.62, round((edge + 5.08) / U) * U)
    top = y - up
    s.wire(x, y, x, top)
    s.power(rail, x, top, 90)
    caps = []
    for i, v in enumerate(values):
        cx = x + dx + side * 12.7 * i
        caps.append(C(s, (cx, top + U + 3.81), v, fp=FP_C0805 if v.endswith("u") and v not in ("1u",) else FP_C0603,
                      text="right" if side > 0 else "left"))
        s.connect(caps[-1], "2", "GND")
        s.path((cx, top), caps[-1].pos("1"))
    s.wire(x, top, x + dx + side * 12.7 * (len(values) - 1), top)
    return caps


def pull(s, x, y, rail, value, up=True, text="auto", **kw):
    """Resistor above (up) or below (down) a point of a horizontal wire, joined by its own short wire."""
    if up:
        r = R(s, (x, y - U - 3.81), value, text=text, **kw)
        s.connect(r, "1", rail)
        s.path((x, y), r.pos("2"))
    else:
        r = R(s, (x, y + U + 3.81), value, text=text, **kw)
        s.connect(r, "2", rail)
        s.path((x, y), r.pos("1"))
    return r


def tap_tp(s, x, y, value):
    """Test point above a wire point, on its own short wire."""
    tp = s.add("Connector:TestPoint", "TP", (x, y - U), value=value, footprint=FP_TP, text="right")
    s.path((x, y), tp.pos("1"))
    return tp


def tap_power(s, net, x, y):
    """Power symbol (rail up / GND down) on a short wire from a wire point."""
    dy = U if net == "GND" else -U
    s.wire(x, y, x, y + dy)
    s.power(net, x, y + dy, 270 if net == "GND" else 90)


def tap_flag(s, x, y):
    fl = s.add("power:PWR_FLAG", "#FLG", (x, y - U))
    s.path((x, y), fl.pos("1"))
    return fl


def r_down(s, x, y, value, **kw):
    """Resistor hanging below a wire point on its own short wire; returns it (bottom pin free)."""
    r = R(s, (x, y + U + 3.81), value, **kw)
    s.path((x, y), r.pos("1"))
    return r


def cap_down(s, x, y, value, **kw):
    """Capacitor to GND below a point of a horizontal wire, joined by its own short wire."""
    c = C(s, (x, y + U + 3.81), value, **kw)
    s.connect(c, "2", "GND")
    s.path((x, y), c.pos("1"))
    return c
