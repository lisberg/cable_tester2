#!/usr/bin/env python3
"""Proto40 schematic: controller + 2 bank sides × (40 fixture nodes + shell + internal test nodes).

Generates hardware/proto40/*.kicad_sch. Edit this file, not the generated schematics.
Run: python3 proto40.py [output_dir]      (KICAD_SYMBOL_DIR = KiCad 10 symbol library directory)

Layout rules: signal flow left → right, functional blocks drawn with wires (decoupling on the power pin,
pull-ups on the line they pull), shared control lines as rails with junctions, net labels only where a net
leaves a block. hardware/gen/layoutcheck.py rejects overlapping text, text on wires and wires through
bodies.

Architecture: docs/design-review-and-kicad-plan.md (F1–F10), fixture pinout: docs/fixture-interface.md,
analog values: hardware/sim/report.md (Rs 4.7 kΩ 1206, Rbias 680 kΩ).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schgen import Project, Sheet
import layoutcheck

PRJ = "proto40"
_ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
OUT = _ARGS[0] if _ARGS else os.path.join(os.path.dirname(__file__), "..", "proto40")
U = 2.54

# ------------------------------------------------------------------------------------------- parts
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


# ------------------------------------------------------------------------------------------- group8
G8_PINS = ([(f"EXT{k}", "passive", "L") for k in range(8)] + [(None, None, "L"), ("MUXOUT", "passive", "L")] +
           [("BIAS_RAIL", "passive", "R"), ("ADDR0", "input", "R"), ("ADDR1", "input", "R"),
            ("ADDR2", "input", "R"), ("EN_N", "input", "R"), ("CLK", "input", "R"), ("PL_N", "input", "R"),
            ("SER_IN", "input", "R"), ("SER_OUT", "output", "R")])


def build_group8():
    """8 symmetric channel cells + 1st-stage 8:1 mux + '165 sense register."""
    s = Sheet("group8", "group8.kicad_sch", PRJ, "Proto40 – 8-channel group")
    s.text("Channel cell (x8):  EXT -> TVS to GND, Rs 4.7 kOhm -> NODE -> Rbias 680 kOhm to BIAS_RAIL, C (DNP).\n"
           "NODE goes to the 1st-stage mux (stimulus / ADC path) and to the '165 (sense bitmap).", 25.4, 15.24)
    X_HL, X_TVS, X_RS, X_RB, X_CF, X_NL, X_RAIL = 27.94, 40.64, 58.42, 72.39, 82.55, 93.98, 106.68
    ys = [43.18 + 30.48 * k for k in range(8)]
    Y_RB = 10.16                                       # Rbias top pin / rail tap above the node line
    for k, y in enumerate(ys):
        s.label(f"EXT{k}", X_HL, y, 180, kind="hier", shape="passive")
        s.wire(X_HL, y, X_RS - 3.81, y)
        tvs = s.add("Device:D_TVS", "D", (X_TVS, y + U + 3.81), rot=90, value="TVS 28V",
                    footprint="Diode_SMD:D_SOD-323",
                    fields={"MPN": "TBD: bidirectional, VRWM >= 28 V, IR <= 100 nA @ 5 V, SOD-323"})
        s.path((X_TVS, y), tvs.pos("2"))
        s.connect(tvs, "1", "GND")
        rs = R(s, (X_RS, y), "4.7k", rot=90, fp=FP_R1206,
               fields={"MPN": "1206 4.7 kΩ 1 % 0.25 W", "Note": "Rs, fault-rated, see sim"})
        rs.pin("1")
        rs.pin("2")
        s.wire(X_RS + 3.81, y, X_NL, y)
        s.label(f"NODE{k}", X_NL, y, 0)
        rb = R(s, (X_RB, y - U - 3.81), "680k", fields={"MPN": "0603 680 kΩ 1 %", "Note": "Rbias, see sim"})
        s.path((X_RB, y), rb.pos("2"))
        s.path(rb.pos("1"), (X_RAIL, y - Y_RB))
        cap_down(s, X_CF, y, "100p", dnp=True)
    s.wire(X_RAIL, ys[0] - Y_RB, X_RAIL, ys[-1] - Y_RB)
    s.wire(X_RAIL, ys[0] - Y_RB, X_RAIL + 7.62, ys[0] - Y_RB)
    s.label("BIAS_RAIL", X_RAIL + 7.62, ys[0] - Y_RB, 0, kind="hier", shape="passive")

    mux = s.add("cable_tester:TMUX1308", "U", (165.1, 96.52), footprint=FP_TSSOP16)
    hier(s, mux, "D", "MUXOUT")
    for k in range(3):
        hier(s, mux, f"SEL{k}", f"ADDR{k}", "input")
    hier(s, mux, "~{E}", "EN_N", "input")
    for k in range(8):
        s.connect(mux, f"S{k}", f"NODE{k}")
    s.connect(mux, "GND", "GND")
    decap(s, mux, "VDD")

    sr = s.add("74xx:74HC165", "U", (271.78, 101.6), footprint=FP_TSSOP16, text="icright",
               fields={"MPN": "SN74HC165PWR", **TI})
    hier(s, sr, "DS", "SER_IN", "input", stub=15.24)
    for k in range(8):
        s.connect(sr, f"D{k}", f"NODE{k}")
    hier(s, sr, "~{PL}", "PL_N", "input")
    hier(s, sr, "CP", "CLK", "input")
    x, y = sr.pos("~{CE}")
    s.path((x, y), (x - U, y), (x - U, y + U))
    s.power("GND", x - U, y + U, 270)
    hier(s, sr, "Q7", "SER_OUT", "output")
    s.connect(sr, "~{Q7}", None)
    s.connect(sr, "GND", "GND")
    decap(s, sr, "VCC", side=-1)
    s.unused_nc()
    return s


# ------------------------------------------------------------------------------------------- side
DIN_FIXED = {"a1": "GND", "a27": "GND", "a28": "SHELL", "a29": "ID_SDA", "a30": "ID_SCL", "a31": "ID_VCC",
             "a32": "GND", "c1": "GND", "c27": "GND", "c28": "PRESENT_N", "c29": "ID_WP", "c30": "ID_A0",
             "c31": "GND", "c32": "GND"}
POPULATED = 40
SIDE_PINS = ([("STIM", "passive", "L"), ("SCK5", "input", "L"), ("RCLK5", "input", "L"), ("PL5_N", "input", "L"),
              ("OE5_N", "input", "L"), ("BIAS_EN_N", "input", "L"), ("CTRL_IN", "input", "L"),
              ("SENSE_IN", "input", "L"), (None, None, "L"), ("ID_A0", "input", "L")] +
             [("CTRL_OUT", "output", "R"), ("SENSE_OUT", "output", "R"), (None, None, "R"),
              ("ID_SDA", "bidirectional", "R"), ("ID_SCL", "bidirectional", "R"), ("ID_WP", "input", "R"),
              ("PRESENT_N", "input", "R"), (None, None, "R"), ("LOOP", "passive", "R")])


def din_net(pin):
    if pin in DIN_FIXED:
        return DIN_FIXED[pin]
    row, n = pin[0], int(pin[1:])
    ch = n - 1 if row == "a" else 25 + n - 1
    return f"EXT{ch:02d}" if ch <= POPULATED else None


def build_side(group8):
    s = Sheet("side", "side.kicad_sch", PRJ, "Proto40 – bank side (fixture connector, 6 groups, 2nd-stage mux)")
    s.text("Fixture connector pinout: docs/fixture-interface.md. EXT41–EXT50 not populated on Proto40.\n"
           "G6 = internal nodes: SHELL, LOOP (wired to the other side), known-open, RREF (100 kOhm to GND).",
           25.4, 12.7)
    # fixture connector
    j = s.add("Connector:DIN41612_02x32_AC", "J", (40.64, 139.7), text="icright",
              footprint="Connector_DIN:DIN41612_C_2x32_Female_Vertical_THT",
              fields={"MPN": "DIN 41612 type C 2x32 female vertical, performance level 1/2"})
    for row in "ac":
        for n in range(1, 33):
            pin = f"{row}{n}"
            net = din_net(pin)
            if net in ("ID_SDA", "ID_SCL", "ID_WP", "ID_A0"):
                hier(s, j, pin, net, "bidirectional" if net.startswith("ID_S") else "input")
            elif net == "PRESENT_N":
                x, y = j.pos(pin)
                s.wire(x, y, x + 25.4, y)
                s.label("PRESENT_N", x + 25.4, y, 0, kind="hier", shape="input")
                pull(s, x + 15.24, y, "+3V3", "10k")
            elif net == "GND":
                s.connect(j, pin, net, rotate=True)
            elif net == "ID_VCC":
                s.connect(j, pin, net, stub=17.78)       # clear of the ID_SCL label above
            else:
                s.connect(j, pin, net, stub=7.62)
    # six groups with control rails
    GX, GW = 101.6, 38.1
    rails = ["BIAS_RAIL", "ADDR1_0", "ADDR1_1", "ADDR1_2", "EN2_N", "SCK5", "PL5_N"]
    gpins = ["BIAS_RAIL", "ADDR0", "ADDR1", "ADDR2", "EN_N", "CLK", "PL_N"]
    xr = [GX + GW + 5.08 * (i + 1) for i in range(len(rails))]
    X_CHAIN, X_OUT = 182.88, 190.5
    groups = []
    for g in range(6):
        gy = 33.02 + 38.1 * g
        sh = s.sheet(f"G{g + 1}", group8, (GX, gy), (GW, U * 11), G8_PINS)
        groups.append(sh)
        for k in range(8):
            if g < 5:
                s.connect(sh, f"EXT{k}", f"EXT{g * 8 + k + 1:02d}")
        s.connect(sh, "MUXOUT", f"MUX{g + 1}")
        for i, p in enumerate(gpins):
            s.path(sh.pin(p)[:2], (xr[i], sh.pin(p)[1]))
    g6 = groups[5]
    s.connect(g6, "EXT0", "SHELL")
    hier(s, g6, "EXT1", "LOOP")
    s.connect(g6, "EXT2", None)
    x, y = g6.pin("EXT3")[:2]
    s.wire(x, y, x - 12.7, y)
    rref = R(s, (x - 12.7, y + 3.81), "100k", text="left", fields={"Note": "load-signature reference node"})
    rref.pin("1")
    s.connect(rref, "2", "GND")
    for k in range(4, 8):
        s.connect(g6, f"EXT{k}", None)
    top = 25.4
    for i, net in enumerate(rails):
        y_last = groups[-1].pin(gpins[i])[1]
        s.wire(xr[i], top, xr[i], y_last)
        s.label(net, xr[i], top, 90, kind="hier" if net == "PL5_N" else "local", shape="input")
    # 165 chain
    for a, b in zip(groups, groups[1:]):
        s.path(a.pin("SER_OUT")[:2], (X_CHAIN, a.pin("SER_OUT")[1]), (X_CHAIN, b.pin("SER_IN")[1]),
               b.pin("SER_IN")[:2])
    s.path(groups[0].pin("SER_IN")[:2], (X_OUT, groups[0].pin("SER_IN")[1]))
    s.label("SENSE_IN", X_OUT, groups[0].pin("SER_IN")[1], 0, kind="hier", shape="input")
    s.path(groups[-1].pin("SER_OUT")[:2], (X_OUT, groups[-1].pin("SER_OUT")[1]))
    s.label("SENSE_OUT", X_OUT, groups[-1].pin("SER_OUT")[1], 0, kind="hier", shape="output")

    # control register
    sr = s.add("74xx:74HC595", "U", (250.19, 53.34), footprint=FP_TSSOP16, fields={"MPN": "SN74HC595PWR", **TI})
    hier(s, sr, "SER", "CTRL_IN", "input", stub=7.62)
    hier(s, sr, "SRCLK", "SCK5", "input", stub=7.62)
    s.connect(sr, "~{SRCLR}", "VDD5", rotate=True)       # sideways: rows above/below are occupied
    hier(s, sr, "RCLK", "RCLK5", "input", stub=7.62)
    hier(s, sr, "~{OE}", "OE5_N", "input", stub=7.62)
    for q, n in zip(["QA", "QB", "QC", "QD", "QE", "QF", "QG", "QH"],
                    ["ADDR1_0", "ADDR1_1", "ADDR1_2", "ADDR2_0", "ADDR2_1", "ADDR2_2", "EN2_N", "BIAS"]):
        s.connect(sr, q, n)
    hier(s, sr, "QH'", "CTRL_OUT", "output", stub=7.62)
    s.connect(sr, "GND", "GND")
    decap(s, sr, "VCC", values=("100n", "10u"))
    # 2nd-stage mux
    m2 = s.add("cable_tester:TMUX1308", "U", (250.19, 119.38), footprint=FP_TSSOP16)
    hier(s, m2, "D", "STIM", stub=7.62)
    for k in range(3):
        s.connect(m2, f"SEL{k}", f"ADDR2_{k}")
    x, y = m2.pos("~{E}")
    s.wire(x, y, x - 33.02, y)
    s.label("EN2_N", x - 33.02, y, 180)
    pull(s, x - 25.4, y, "VDD5", "100k", text="left", fields={"Note": "mux off while 595 outputs are Hi-Z"})
    for g in range(6):
        s.connect(m2, f"S{g}", f"MUX{g + 1}")
    x, y = m2.pos("S6")
    s.wire(x, y, x + 12.7, y)
    pull(s, x + 12.7, y, "VDD5", "100k")
    pull(s, x + 12.7, y, "GND", "100k", up=False)
    s.label("STIM_CAL", x + 2.54, y, 0)
    s.connect(m2, "S7", None)
    s.connect(m2, "GND", "GND")
    decap(s, m2, "VDD")
    # bias rail driver
    bd = s.add("74xGxx:74AHCT1G125", "U", (256.54, 180.34), footprint=FP_SOT235, text="icright",
               fields={"MPN": "SN74AHCT1G125DBVR", **TI})
    x, y = bd.pos("2")
    s.wire(x, y, x - 17.78, y)
    s.label("BIAS", x - 17.78, y, 180)
    pull(s, x - 7.62, y, "GND", "100k", up=False, fields={"Note": "bias low while 595 outputs are Hi-Z"})
    x, y = bd.pos("1")
    s.path((x, y), (x, y - 7.62), (x + 20.32, y - 7.62))
    s.label("BIAS_EN_N", x + 20.32, y - 7.62, 0, kind="hier", shape="input")
    pull(s, x + 10.16, y - 7.62, "VDD5", "100k", fields={"Note": "bias Hi-Z until the MCU enables it"})
    decap(s, bd, "VCC", side=-1, up=12.7)
    s.connect(bd, "GND", "GND")
    x, y = bd.pos("4")
    s.wire(x, y, x + 27.94, y)
    s.label("BIAS_RAIL", x + 27.94, y, 0)
    tap_tp(s, x + 10.16, y, "BIAS_RAIL")
    # fixture ID supply
    rid = R(s, (232.41, 228.6), "47", rot=90, fields={"Note": "ID_VCC current limit"})
    x1, y1 = rid.pos("1")
    s.wire(x1, y1, x1 - 5.08, y1)
    s.power("+3V3", x1 - 5.08, y1, 90)
    x2, y2 = rid.pos("2")
    s.wire(x2, y2, x2 + 17.78, y2)
    s.label("ID_VCC", x2 + 17.78, y2, 0)
    cap_down(s, x2 + 7.62, y2, "100n")
    s.unused_nc()
    return s


# ------------------------------------------------------------------------------------------- control
CTRL_IN_PINS = ["SCK", "MOSI", "MISO", "RCLK", "PL_N", "OE_N", "BIAS_EN_N", "STIM_DRV", "STIM_EN_N", "ADC_STIM",
                "ADC_VDD5"]
CTRL_PINS = ([(n, "output" if n in ("MISO", "ADC_STIM", "ADC_VDD5") else "input", "L") for n in CTRL_IN_PINS] +
             [("STIM", "passive", "R"), ("SCK5", "output", "R"), ("RCLK5", "output", "R"),
              ("PL5_N", "output", "R"), ("OE5_N", "output", "R"), ("BIAS_EN5_N", "output", "R"),
              ("MOSI5", "output", "R"), ("SENSE_LAST", "input", "R")])


def unit_pins(unit):
    """(A, ~OE, Y) pin numbers of a 74xx125 unit."""
    return {1: ("2", "1", "3"), 2: ("5", "4", "6"), 3: ("9", "10", "8"), 4: ("12", "13", "11")}[unit.unit]


def build_control():
    s = Sheet("control", "control.kicad_sch", PRJ, "Proto40 – level shifting, stimulus driver, ADC taps")
    s.text("MCU (3.3 V) -> 5 V logic: 74AHCT125 (TTL input levels).   5 V sense chain -> MCU: 74LVC1G125 at 3.3 V.\n"
           "Pull-ups keep OE5_N, BIAS_EN and STIM_EN inactive while the MCU is in reset (review F6).", 25.4, 12.7)
    # level shifters
    for col, (x0, pairs) in enumerate([(66.04, [("SCK", "SCK5"), ("MOSI", "MOSI5"), ("RCLK", "RCLK5"),
                                                 ("PL_N", "PL5_N")]),
                                       (180.34, [("OE_N", "OE5_N"), ("BIAS_EN_N", "BIAS_EN5_N"), (None, None),
                                                 (None, None)])]):
        units = []
        for u in range(5):
            units.append(s.add("74xx:74AHCT125", "U", (x0, 40.64 + 25.4 * u + (25.4 if u == 4 else 0)),
                               unit=u + 1, footprint=FP_TSSOP14, text="icright",
                               same_as=units[0] if units else None, fields={"MPN": "SN74AHCT125PWR", **TI}))
        for unit, (src, dst) in zip(units[:4], pairs):
            a, oe, yp = unit_pins(unit)
            if src is None:
                s.connect(unit, a, "GND", stub=5.08)        # unused gate: input and enable tied low
                s.connect(unit, oe, "GND")
                s.connect(unit, yp, None)
                continue
            xa, ya = unit.pos(a)
            s.wire(xa, ya, xa - 20.32, ya)
            s.label(src, xa - 20.32, ya, 180, kind="hier", shape="input")
            if col == 1:
                pull(s, xa - 10.16, ya, "+3V3", "10k", fields={"Note": "inactive during MCU reset"})
            s.connect(unit, oe, "GND")
            hier(s, unit, yp, dst, "output", stub=15.24)
        s.connect(units[4], "GND", "GND")
        decap(s, units[4], "VCC", side=-1)
    # MISO return buffer (3.3 V)
    mb = s.add("74xGxx:74LVC1G125", "U", (83.82, 220.98), footprint=FP_SOT235, text="icright", fields={"MPN": "SN74LVC1G125DBVR", **TI})
    hier(s, mb, "2", "SENSE_LAST", "input", stub=10.16)
    x, y = mb.pos("1")
    s.path((x, y), (x, y - 5.08), (x + 15.24, y - 5.08), (x + 15.24, y - 2.54))
    s.power("GND", x + 15.24, y - 2.54, 270)
    hier(s, mb, "4", "MISO", "output", stub=10.16)
    decap(s, mb, "VCC", rail="+3V3", side=-1)
    s.connect(mb, "GND", "GND")
    # stimulus driver
    sd = s.add("74xGxx:74AHCT1G125", "U", (190.5, 220.98), footprint=FP_SOT235, text="icright", fields={"MPN": "SN74AHCT1G125DBVR", **TI})
    hier(s, sd, "2", "STIM_DRV", "input", stub=10.16)
    x, y = sd.pos("1")
    s.path((x, y), (x, y - 7.62), (x + 25.4, y - 7.62))
    s.label("STIM_EN_N", x + 25.4, y - 7.62, 0, kind="hier", shape="input")
    pull(s, x + 12.7, y - 7.62, "+3V3", "10k", fields={"Note": "stimulus off during MCU reset"})
    decap(s, sd, "VCC", side=-1)
    s.connect(sd, "GND", "GND")
    xs, ys = sd.pos("4")
    rl = R(s, (xs + 7.62, ys), "150", rot=90, fields={"Note": "Rlim"})
    s.path((xs, ys), rl.pos("1"))
    x2, _ = rl.pos("2")
    s.wire(x2, ys, x2 + 30.48, ys)
    s.label("STIM", x2 + 30.48, ys, 0, kind="hier", shape="passive")
    tap_tp(s, x2 + 7.62, ys, "STIM")
    # ADC dividers: STIM and VDD5
    for src_x, top_net, adc in ((x2 + 17.78, None, "ADC_STIM"), (x2 + 50.8, "VDD5", "ADC_VDD5")):
        if top_net:
            r1 = R(s, (src_x, ys + 3.81), "100k")
            s.connect(r1, "1", "VDD5", stub=0)
        else:
            r1 = r_down(s, src_x, ys, "100k")
        n = r1.pos("2")
        pull(s, n[0], n[1], "GND", "100k", up=False, text="left")
        s.wire(n[0], n[1], n[0] + 15.24, n[1])
        cap_down(s, n[0] + 7.62, n[1], "1n")
        s.label(adc, n[0] + 15.24, n[1], 0, kind="hier", shape="output")
    s.unused_nc()
    return s


# ------------------------------------------------------------------------------------------- mcu
MCU_HIER_R = [("SCK", "PA5", "output"), ("MOSI", "PA7", "output"), ("MISO", "PA6", "input"),
              ("RCLK", "PB0", "output"), ("PL_N", "PB1", "output"), ("OE_N", "PB2", "output"),
              ("BIAS_EN_N", "PB4", "output"), ("STIM_DRV", "PA8", "output"), ("STIM_EN_N", "PB3", "output"),
              ("ADC_STIM", "PA0", "input"), ("ADC_VDD5", "PA1", "input"), (None, None, None),
              ("ID_SDA", "PB7", "bidirectional"), ("ID_SCL", "PB6", "bidirectional"),
              ("ID_WP_A", "PB12", "output"), ("ID_WP_B", "PB13", "output"),
              ("PRESENT_A_N", "PB14", "input"), ("PRESENT_B_N", "PB15", "input")]
MCU_PINS = ([("USB_DP", "bidirectional", "L"), ("USB_DM", "bidirectional", "L")] +
            [(n, t, "R") for n, _, t in MCU_HIER_R])
MCU_LOCAL = {"PA2": "LED_PASS", "PA3": "LED_FAIL", "PA4": "LED_BUSY", "PA9": "UART_TX", "PA10": "UART_RX",
             "PA13": "SWDIO", "PA14": "SWCLK", "PA15": "BUZZER"}


def build_mcu():
    s = Sheet("mcu", "mcu.kicad_sch", PRJ, "Proto40 – STM32C071 controller, UI, debug")
    s.text("Alternate functions to confirm in STM32CubeMX: SPI1 PA5/6/7, I2C1 PB6/7, USB PA11/12, ADC PA0/1.",
           25.4, 12.7)
    u = s.add("MCU_ST_STM32C0:STM32C071C8Tx", "U", (139.7, 139.7),
              fields={"MPN": "STM32C071C8T6", "Manufacturer": "STMicroelectronics"})
    for net, pin, shape in MCU_HIER_R:
        if net:
            hier(s, u, pin, net, shape, stub=7.62)
    for pin, net in MCU_LOCAL.items():          # long stubs: clear of the hierarchical labels on adjacent pins
        s.connect(u, pin, net, stub=25.4)
    hier(s, u, "PA11", "USB_DM", "bidirectional", stub=7.62)
    hier(s, u, "PA12", "USB_DP", "bidirectional", stub=7.62)
    s.connect(u, "VSS", "GND")
    decap(s, u, "VDD", rail="+3V3", values=("100n", "100n", "4.7u"))
    x, y = u.pos("VREF+")
    s.path((x, y), (x - 7.62, y), (x - 7.62, y - 15.24))
    s.power("+3V3", x - 7.62, y - 15.24, 90)
    s.wire(x - 7.62, y - 12.7, x - 17.78, y - 12.7)
    cap_down(s, x - 17.78, y - 12.7, "100n", text="left")
    # reset
    x, y = u.pos("PF2")
    s.wire(x, y, x - 25.4, y)
    s.label("NRST", x - 25.4, y, 180)
    cap_down(s, x - 17.78, y, "100n", text="left")
    # start button
    x, y = u.pos("PC13")
    s.wire(x, y, x - 33.02, y)
    pull(s, x - 7.62, y, "+3V3", "10k", text="left")
    cap_down(s, x - 17.78, y, "100n", text="left")
    sw = s.add("Switch:SW_Push", "SW", (x - 38.1, y), value="START", footprint="Button_Switch_SMD:SW_SPST_TL3342")
    sw.pin("2")
    x1, y1 = sw.pos("1")
    s.path((x1, y1), (x1 - 2.54, y1), (x1 - 2.54, y1 + 2.54))
    s.power("GND", x1 - 2.54, y1 + 2.54, 270)
    # LEDs
    for i, (net, col) in enumerate([("LED_PASS", "green"), ("LED_FAIL", "red"), ("LED_BUSY", "yellow")]):
        y = 45.72 + 17.78 * i
        s.label(net, 241.3, y, 180)
        rl = R(s, (251.46, y), "1k", rot=90)
        s.path((241.3, y), rl.pos("1"))
        xl = rl.pos("2")[0] + 5.08
        led = s.add("Device:LED", "D", (xl, y + 3.81), rot=90, value=col, footprint="LED_SMD:LED_0603_1608Metric")
        s.path(rl.pos("2"), led.pos("A"))
        s.connect(led, "K", "GND", stub=5.08)
    # buzzer
    bz = s.add("Device:Buzzer", "BZ", (256.54, 111.76), footprint="Buzzer_Beeper:Buzzer_12x9.5RM7.6",
               fields={"Note": "passive piezo, GPIO PWM"})
    x, y = bz.pos("1")
    s.wire(x, y, x - 12.7, y)
    s.label("BUZZER", x - 12.7, y, 180)
    x, y = bz.pos("2")
    s.path((x, y), (x - 5.08, y), (x - 5.08, y + 2.54))
    s.power("GND", x - 5.08, y + 2.54, 270)
    # SWD
    swd = s.add("Connector:Conn_ARM_SWD_TagConnect_TC2030", "J", (251.46, 139.7),
                footprint="Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical", text="icright")
    s.connect(swd, "VCC", "+3V3")
    s.connect(swd, "GND", "GND")
    s.nets(swd, {"SWDIO": "SWDIO", "SWCLK": "SWCLK", "~{RESET}": "NRST", "SWO": None})
    # UART
    uart = s.add("Connector_Generic:Conn_01x03", "J", (264.16, 180.34), value="UART",
                 footprint="Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", text="icright")
    s.connect(uart, "1", "UART_TX", stub=7.62)
    s.connect(uart, "2", "UART_RX", stub=7.62)
    x, y = uart.pos("3")
    s.path((x, y), (x - 2.54, y), (x - 2.54, y + 2.54))
    s.power("GND", x - 2.54, y + 2.54, 270)
    # I2C pull-ups for the fixture EEPROMs
    for i, net in enumerate(["ID_SDA", "ID_SCL"]):
        x = 248.92 + 12.7 * i
        r = R(s, (x, 220.98), "4.7k")
        s.connect(r, "1", "+3V3", stub=0)
        xb, yb = r.pos("2")
        s.wire(xb, yb, xb, yb + 5.08)
        s.label(net, xb, yb + 5.08, 270)
    s.unused_nc()
    return s


# ------------------------------------------------------------------------------------------- power
def build_power():
    s = Sheet("power", "power.kicad_sch", PRJ, "Proto40 – USB-C power, VDD5 shunt clamp, 3.3 V")
    s.text("VBUS -> PTC -> LM66100 ideal diode (never back-feeds the host) -> ferrite -> VDD5.\n"
           "TL431 + BCP53 shunt clamp holds VDD5 <= 5.45 V when fixture faults inject current (review F9).",
           25.4, 12.7)
    j = s.add("Connector:USB_C_Receptacle_USB2.0_16P", "J", (40.64, 101.6), text="icright",
              footprint="Connector_USB:USB_C_Receptacle_HCTL_HC-TYPE-C-16P-01A")
    for pin in ("A9", "B4", "B9", "A12", "B1", "B12"):
        j.pin(pin)
    s.connect(j, "A5", "CC1", stub=5.08)
    s.connect(j, "B5", "CC2", stub=10.16)
    s.connect(j, "A8", None)
    s.connect(j, "B8", None)
    s.connect(j, "A1", "GND")
    # D+/D- pairs joined, then through the ESD array
    (xa7, ya7), (xb7, yb7) = j.pos("A7"), j.pos("B7")
    (xa6, ya6), (xb6, yb6) = j.pos("A6"), j.pos("B6")
    s.path((xa7, ya7), (xa7 + 5.08, ya7), (xa7 + 5.08, yb7), (xb7, yb7))
    s.path((xa6, ya6), (xa6 + 2.54, ya6), (xa6 + 2.54, yb6), (xb6, yb6))
    esd = s.add("Power_Protection:USBLC6-2SC6", "U", (91.44, 101.6), fields={"MPN": "USBLC6-2SC6"})
    s.path((xa7 + 5.08, ya7), (xa7 + 20.32, ya7), (xa7 + 20.32, esd.pos("1")[1]), esd.pos("1"))
    s.path((xa6 + 2.54, yb6), (xa6 + 22.86, yb6), (xa6 + 22.86, esd.pos("3")[1]), esd.pos("3"))
    hier(s, esd, "6", "USB_DM", "bidirectional", stub=10.16)
    hier(s, esd, "4", "USB_DP", "bidirectional", stub=10.16)
    s.connect(esd, "2", "GND")
    x, y = esd.pos("5")
    s.wire(x, y, x, y - 5.08)
    s.label("VBUS_F", x, y - 5.08, 90)
    # CC pull-downs
    for i, net in enumerate(["CC1", "CC2"]):
        x = 30.48 + 10.16 * i
        r = R(s, (x, 60.96), "5.1k")
        s.wire(*r.pos("1"), x, 53.34)
        s.label(net, x, 53.34, 90)
        s.connect(r, "2", "GND")
    # shield
    xs, ys = j.pos("SH")
    s.wire(xs, ys, xs, ys + 5.08)
    s.wire(xs, ys + 5.08, xs - 12.7, ys + 5.08)
    rsh = r_down(s, xs - 5.08, ys + 5.08, "1M", text="right")
    s.connect(rsh, "2", "GND")
    cap_down(s, xs - 12.7, ys + 5.08, "4.7n", text="left", fields={"Note": "≥ 100 V"})
    # VBUS → PTC → ideal diode → ferrite → VDD5
    yv = 78.74
    xv, yvb = j.pos("A4")
    s.path((xv, yvb), (xv + 7.62, yvb), (xv + 7.62, yv))
    s.power("VBUS", xv + 7.62, yv, 90)
    tap_flag(s, xv + 20.32, yv)
    f = s.add("Device:Polyfuse", "F", (91.44, yv), rot=90, value="500mA", footprint="Fuse:Fuse_1206_3216Metric",
              fields={"MPN": "1206 PTC 500 mA hold, 6 V"})
    s.path((xv + 7.62, yv), f.pos("1"))
    idd = s.add("Power_Management:LM66100DCK", "U", (139.7, yv + 2.54), text="icright",
                fields={"MPN": "LM66100DCKR"})
    s.path(f.pos("2"), idd.pos("VIN"))
    xf2 = f.pos("2")[0]
    tap_flag(s, xf2 + 6.35, yv)
    s.wire(xf2 + 16.51, yv, xf2 + 16.51, yv - 5.08)
    s.label("VBUS_F", xf2 + 16.51, yv - 5.08, 90)
    cap_down(s, xf2 + 22.86, yv, "10u", fp=FP_C0805, text="left")
    x, y = idd.pos("~{CE}")
    s.path((x, y), (x - 2.54, y), (x - 2.54, y + 7.62))
    s.power("GND", x - 2.54, y + 7.62, 270)
    s.connect(idd, "GND", "GND")
    s.connect(idd, "ST", None)
    fb = s.add("Device:FerriteBead", "FB", (157.48, yv), rot=90, value="600R@100MHz", text="below",
               footprint="Inductor_SMD:L_0603_1608Metric", fields={"Note": "≥ 1 A"})
    s.path(idd.pos("VOUT"), fb.pos("1"))
    xr0 = fb.pos("2")[0]
    tap_power(s, "VDD5", xr0 + 12.7, yv)
    tap_flag(s, xr0 + 20.32, yv)
    for i, v in enumerate(["10u", "10u", "100n"]):
        cap_down(s, xr0 + 27.94 + 12.7 * i, yv, v, fp=FP_C0805 if v == "10u" else FP_C0603)
    tap_tp(s, xr0 + 63.5, yv, "VDD5")
    # shunt clamp: PNP on VDD5, TL431 sets ~5.45 V
    q = s.add("Transistor_BJT:BCP53", "Q", (xr0 + 80.01, 93.98), rot=180, text="left",
              fields={"MPN": "BCP53-16", "Note": "shunt pass, ≥ 1 W"})
    xe, ye = q.pos("E")
    s.wire(xe, ye, xe, yv)
    xc, yc = q.pos("2")
    s.path(q.pos("4"), (xc, q.pos("4")[1]))
    rce = r_down(s, xc, yc, "4.7", fp=FP_R1206, text="left", fields={"Note": "collector ballast"})
    s.connect(rce, "2", "GND")
    xb, yb = q.pos("B")
    XN = xb + 7.62
    rbe = r_down(s, XN, yv, "10k")
    s.path(rbe.pos("2"), (XN, yb), (xb, yb))
    s.label("CLAMP_B", XN, yb, 0)
    XT = XN + 12.7
    s.path((XN, yb), (XN, yb + 2.54), (XT, yb + 2.54))
    rbk = R(s, (XT, yb + 6.35), "470")
    rbk.pin("1")
    tl = s.add("Reference_Voltage:TL431DBZ", "U", (XT, yb + 15.24), rot=90, fields={"MPN": "TL431BIDBZR"})
    s.path(rbk.pos("2"), tl.pos("K"))
    s.connect(tl, "A", "GND")
    xref, yref = tl.pos("REF")
    XD = XT + 15.24
    YD = yref + 12.7
    s.path((xref, yref), (xref - 2.54, yref), (xref - 2.54, YD), (XD, YD))
    s.wire(xr0, yv, XD, yv)
    rt = r_down(s, XD, yv, "11.8k", fields={"Note": "sets clamp ≈ 5.45 V"})
    s.path(rt.pos("2"), (XD, YD))
    pull(s, XD, YD, "GND", "10k", up=False)
    # 3.3 V LDO
    ldo = s.add("Regulator_Linear:AP2112K-3.3", "U", (190.5, 165.1), text="icright",
                fields={"MPN": "AP2112K-3.3TRG1"})
    xi, yi = ldo.pos("VIN")
    s.wire(xi, yi, xi - 20.32, yi)
    s.power("VDD5", xi - 20.32, yi, 90)
    xe2, ye2 = ldo.pos("EN")
    s.path((xe2, ye2), (xe2 - 5.08, ye2), (xe2 - 5.08, yi))
    cap_down(s, xi - 12.7, yi, "1u", text="left")
    s.connect(ldo, "GND", "GND")
    s.connect(ldo, "NC", None)
    xo, yo = ldo.pos("VOUT")
    s.wire(xo, yo, xo + 25.4, yo)
    tap_power(s, "+3V3", xo + 7.62, yo)
    cap_down(s, xo + 15.24, yo, "1u")
    s.wire(xo + 25.4, yo, xo + 27.94, yo)
    tp2 = s.add("Connector:TestPoint", "TP", (xo + 27.94, yo - U), value="+3V3", footprint=FP_TP, text="right")
    s.path((xo + 27.94, yo), tp2.pos("1"))
    tp3 = s.add("Connector:TestPoint", "TP", (241.3, 190.5), value="GND", footprint=FP_TP, text="right")
    s.connect(tp3, "1", "GND")
    fg = s.add("power:PWR_FLAG", "#FLG", (63.5, 132.08))
    s.connect(fg, "1", "GND")
    s.unused_nc()
    return s


# ------------------------------------------------------------------------------------------- root
def build():
    g8 = build_group8()
    side = build_side(g8)
    ctrl = build_control()
    mcu = build_mcu()
    pwr = build_power()
    root = Sheet("root", "proto40.kicad_sch", PRJ, "Cable Tester Proto40", paper="A3")
    root.text("Proto40: STM32C071 controller + 2 x (40 fixture nodes + shell + internal test nodes).\n"
              "Generated by hardware/gen/proto40.py. Architecture: docs/design-review-and-kicad-plan.md.", 25.4, 12.7)
    TOP = 45.72
    p = root.sheet("Power", pwr, (20.32, TOP), (25.4, U * 3), [("USB_DP", "bidirectional", "R"),
                                                               ("USB_DM", "bidirectional", "R")])
    m = root.sheet("MCU", mcu, (71.12, TOP), (38.1, U * 19), MCU_PINS)
    cs = root.sheet("Control", ctrl, (160.02, TOP), (33.02, U * 12), CTRL_PINS)
    sa = root.sheet("SideA", side, (251.46, TOP), (35.56, U * 11), SIDE_PINS)
    sb = root.sheet("SideB", side, (251.46, TOP + 76.2), (35.56, U * 11), SIDE_PINS)
    for n in ("USB_DP", "USB_DM"):
        root.path(p.pin(n)[:2], m.pin(n)[:2])
    for n in CTRL_IN_PINS:
        root.path(m.pin(n)[:2], cs.pin(n)[:2])
    # control → both sides: shared nets as rails
    shared = [("STIM", "STIM"), ("SCK5", "SCK5"), ("RCLK5", "RCLK5"), ("PL5_N", "PL5_N"), ("OE5_N", "OE5_N"),
              ("BIAS_EN5_N", "BIAS_EN_N")]
    for i, (cp, sp) in enumerate(shared):
        x = 208.28 + 5.08 * i
        yc = cs.pin(cp)[1]
        root.path(cs.pin(cp)[:2], (x, yc))
        root.path((x, yc), sa.pin(sp)[:2])
        root.path((x, yc), (x, sb.pin(sp)[1]), sb.pin(sp)[:2])
    root.path(cs.pin("MOSI5")[:2], sa.pin("CTRL_IN")[:2])
    root.connect(cs, "SENSE_LAST", "SENSE_LAST")
    root.connect(sa, "SENSE_IN", "GND", rotate=True, stub=5.08)   # sideways: dense pin column
    root.connect(sa, "ID_A0", "GND", rotate=True, stub=5.08)
    root.connect(sb, "CTRL_IN", "CTRL_AB")
    root.connect(sb, "SENSE_IN", "SENSE_AB")
    root.connect(sb, "ID_A0", "+3V3", rotate=True, stub=5.08)
    root.connect(sa, "CTRL_OUT", "CTRL_AB")
    root.connect(sa, "SENSE_OUT", "SENSE_AB")
    root.connect(sb, "CTRL_OUT", None)
    root.connect(sb, "SENSE_OUT", "SENSE_LAST")
    for sh, tag in ((sa, "A"), (sb, "B")):
        root.nets(sh, {"ID_SDA": "ID_SDA", "ID_SCL": "ID_SCL", "ID_WP": f"ID_WP_{tag}",
                       "PRESENT_N": f"PRESENT_{tag}_N"})
    for n in ("ID_SDA", "ID_SCL", "ID_WP_A", "ID_WP_B", "PRESENT_A_N", "PRESENT_B_N"):
        root.connect(m, n, n)
    xa, ya = sa.pin("LOOP")[:2]
    xb, yb = sb.pin("LOOP")[:2]
    root.path((xa, ya), (xa + 27.94, ya), (xa + 27.94, yb), (xb, yb))
    root.text("LOOP: side A G6 node 1 is hard-wired\nto side B G6 node 1 (known-good\npath for self-test).",
              xa + 30.48, (ya + yb) / 2 - 5.08)

    bases = {(): 0, ("Power",): 100, ("MCU",): 200, ("Control",): 300, ("SideA",): 1000, ("SideB",): 2000}

    def base_of(names):
        if names in bases:
            return bases[names]
        return bases[names[:1]] + 100 * int(names[1][1:])

    sheets = [root, pwr, mcu, ctrl, side, g8]
    problems = 0
    for sh in sheets:
        issues = layoutcheck.check(sh)
        for i in issues:
            print(f"[{sh.filename}] {i}")
        problems += len(issues)
    Project(PRJ, root, base_of).write(OUT)
    return problems


if __name__ == "__main__":
    n = build()
    print(f"layout issues: {n}")
    sys.exit(1 if n and "--strict" in sys.argv else 0)
