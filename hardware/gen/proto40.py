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

from style import (U, FP_R0603, FP_R1206, FP_R2512, FP_C0603, FP_C0805, FP_TSSOP16, FP_TSSOP14, FP_SOT235, FP_TP,
                   TI, NO_PART, R, C, hier, decap, pull, tap_tp, tap_power, tap_flag, r_down, cap_down)


# ------------------------------------------------------------------------------------------- group8
G8_PINS = ([(f"EXT{k}", "passive", "L") for k in range(8)] + [(None, None, "L"), ("MUXOUT", "passive", "L")] +
           [("BIAS_RAIL", "passive", "R"), ("ADDR0", "input", "R"), ("ADDR1", "input", "R"),
            ("ADDR2", "input", "R"), ("EN_N", "input", "R"), ("CLK", "input", "R"), ("PL_N", "input", "R"),
            ("SER_IN", "input", "R"), ("SER_OUT", "output", "R")])


def build_group8():
    """8 symmetric channel cells + 1st-stage 8:1 mux + '165 sense register."""
    s = Sheet("group8", "group8.kicad_sch", PRJ, "Proto40 - 8-channel group")
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
        rs = R(s, (X_RS, y), "4.7k", rot=90, fp=FP_R1206, fields={"Note": "Rs, 0.25 W, fault-rated, see sim"})
        rs.pin("1")
        rs.pin("2")
        s.wire(X_RS + 3.81, y, X_NL, y)
        s.label(f"NODE{k}", X_NL, y, 0)
        rb = R(s, (X_RB, y - U - 3.81), "680k", fields={"Note": "Rbias, see sim"})
        s.path((X_RB, y), rb.pos("2"))
        s.path(rb.pos("1"), (X_RAIL, y - Y_RB))
        cap_down(s, X_CF, y, "100p", dnp=True)
    s.wire(X_RAIL, ys[0] - Y_RB, X_RAIL, ys[-1] - Y_RB)
    s.wire(X_RAIL, ys[0] - Y_RB, X_RAIL + 7.62, ys[0] - Y_RB)
    s.label("BIAS_RAIL", X_RAIL + 7.62, ys[0] - Y_RB, 0, kind="hier", shape="passive")

    mux = s.add("cable_tester:TMUX1308", "U", (152.4, 96.52), footprint=FP_TSSOP16)
    hier(s, mux, "D", "MUXOUT")
    for k in range(3):
        hier(s, mux, f"SEL{k}", f"ADDR{k}", "input")
    hier(s, mux, "~{E}", "EN_N", "input")
    for k in range(8):
        s.connect(mux, f"S{k}", f"NODE{k}")
    s.connect(mux, "GND", "GND")
    decap(s, mux, "VDD")

    sr = s.add("74xx:74HC165", "U", (241.3, 101.6), footprint=FP_TSSOP16, text="ic",
               fields={"MPN": "SN74HC165PWR", **TI})
    x, y = sr.pos("DS")                                    # jog up: the line must not run over the NODE0 label
    s.path((x, y), (x - U, y), (x - U, y - 5.08), (x - 15.24, y - 5.08))
    s.label("SER_IN", x - 15.24, y - 5.08, 180, kind="hier", shape="input")
    for k in range(8):
        s.connect(sr, f"D{k}", f"NODE{k}")
    hier(s, sr, "~{PL}", "PL_N", "input")
    hier(s, sr, "CP", "CLK", "input")
    x, y = sr.pos("~{CE}")
    s.path((x, y), (x - 7.62, y), (x - 7.62, y + U))       # GND clear of the value text under the body
    s.power("GND", x - 7.62, y + U, 270)
    hier(s, sr, "Q7", "SER_OUT", "output")
    s.connect(sr, "~{Q7}", None)
    s.connect(sr, "GND", "GND")
    decap(s, sr, "VCC")                                    # right side: the SER_IN jog uses the left
    s.unused_nc()
    return s


# ------------------------------------------------------------------------------------------- side
DIN_FIXED = {"a1": "GND", "a27": "GND", "a28": "SHELL", "a29": "ID_SDA_EXT", "a30": "ID_SCL_EXT",
             "a31": "ID_VCC_EXT", "a32": "GND", "c1": "GND", "c27": "GND", "c28": "PRESENT_N_EXT",
             "c29": "ID_WP_EXT", "c30": "ID_A0_EXT", "c31": "GND", "c32": "GND"}
POPULATED = 40
# Left pins line up with the root sheet: chain inputs (rows 1-2) are fed from SideA by wire, the control rails
# (rows 3-8) come straight from Control, the fixture-ID lines (rows 14-17) straight from the MCU.
SIDE_PINS = ([("CTRL_IN", "input", "L"), ("SENSE_IN", "input", "L"), ("STIM", "passive", "L"),
              ("SCK5", "input", "L"), ("RCLK5", "input", "L"), ("PL5_N", "input", "L"), ("OE5_N", "input", "L"),
              ("BIAS_EN_N", "input", "L"), (None, None, "L"), ("ID_A0", "input", "L"), (None, None, "L"),
              (None, None, "L"), (None, None, "L"), ("ID_SDA", "bidirectional", "L"),
              ("ID_SCL", "bidirectional", "L"), ("ID_WP", "input", "L"), ("PRESENT_N", "output", "L")] +
             [("LOOP", "passive", "R"), (None, None, "R"), ("CTRL_OUT", "output", "R"),
              ("SENSE_OUT", "output", "R")])
ESD = {"MPN": "PESD5V0S1BA", "Manufacturer": "Nexperia", "Note": "ESD, fixture ID line"}


def din_net(pin):
    if pin in DIN_FIXED:
        return DIN_FIXED[pin]
    row, n = pin[0], int(pin[1:])
    ch = n - 1 if row == "a" else 25 + n - 1
    return f"EXT{ch:02d}" if ch <= POPULATED else None


def id_line(s, x0, y, ext, net, shape, r_value, pullup=False):
    """Fixture ID line: connector-side label -> ESD diode to GND -> series R -> hierarchical label.
    ESD and R keep miswiring/ESD on the adapter away from the 3.3 V MCU pins (docs/decisions.md D14)."""
    s.label(ext, x0, y, 180)
    s.wire(x0, y, x0 + 13.97, y)
    tvs = s.add("Device:D_TVS", "D", (x0 + 5.08, y + U + 3.81), rot=90, value="ESD 5V",
                footprint="Diode_SMD:D_SOD-323", fields=ESD)
    s.path((x0 + 5.08, y), tvs.pos("2"))
    s.connect(tvs, "1", "GND")
    rs = R(s, (x0 + 17.78, y), r_value, rot=90, fields={"Note": "series R, fixture ID line"})
    rs.pin("1")
    rs.pin("2")
    s.wire(x0 + 21.59, y, x0 + 30.48, y)
    if pullup:
        pull(s, x0 + 25.4, y, "+3V3", "10k", fields={"Note": "adapter ties PRESENT_N to GND"})
    s.label(net, x0 + 30.48, y, 0, kind="hier", shape=shape)


def build_side(group8):
    s = Sheet("side", "side.kicad_sch", PRJ, "Proto40 - bank side: connector, 6 groups, 2nd-stage mux")
    s.text("Fixture connector pinout: docs/fixture-interface.md. EXT41-EXT50 not populated.\n"
           "G6 = internal nodes: SHELL, LOOP (wired to the other side),\n"
           "known-open, RREF (100 kOhm to GND).", 25.4, 12.7)
    # fixture connector: every pin to a label (dense pin column); the ID lines go to the ID block (right)
    j = s.add("Connector:DIN41612_02x32_AC", "J", (40.64, 139.7), text="icright",
              footprint="Connector_DIN:DIN41612_C_2x32_Female_Vertical_THT",
              fields={"MPN": "TBD: DIN 41612 type C 2x32 female vertical, performance level 1/2"})
    for row in "ac":
        for n in range(1, 33):
            pin = f"{row}{n}"
            net = din_net(pin)
            if net == "GND":
                s.connect(j, pin, net, rotate=True)
            else:                                        # label text starts beyond the GND texts
                s.connect(j, pin, net, stub=10.16)
    # six groups with control rails
    GX, GW = 101.6, 38.1
    rails = ["BIAS_RAIL", "ADDR1_0", "ADDR1_1", "ADDR1_2", "EN2_N", "SCK5", "PL5_N"]
    gpins = ["BIAS_RAIL", "ADDR0", "ADDR1", "ADDR2", "EN_N", "CLK", "PL_N"]
    xr = [GX + GW + 5.08 * (i + 1) for i in range(len(rails))]
    X_CHAIN, X_TP, X_OUT = 182.88, 187.96, 205.74
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
    # 165 chain, with test points on chain in / out
    for a, b in zip(groups, groups[1:]):
        s.path(a.pin("SER_OUT")[:2], (X_CHAIN, a.pin("SER_OUT")[1]), (X_CHAIN, b.pin("SER_IN")[1]),
               b.pin("SER_IN")[:2])
    for sh, pin, net, shape in ((groups[0], "SER_IN", "SENSE_IN", "input"),
                                (groups[-1], "SER_OUT", "SENSE_OUT", "output")):
        x, y = sh.pin(pin)[:2]
        s.path((x, y), (X_OUT, y))
        tap_tp(s, X_TP, y, net)
        s.label(net, X_OUT, y, 0, kind="hier", shape=shape)

    # control register
    sr = s.add("74xx:74HC595", "U", (250.19, 53.34), footprint=FP_TSSOP16, fields={"MPN": "SN74HC595PWR", **TI})
    x, y = sr.pos("SER")
    s.wire(x, y, x - 20.32, y)
    tap_tp(s, x - 15.24, y, "CTRL_IN")
    s.label("CTRL_IN", x - 20.32, y, 180, kind="hier", shape="input")
    hier(s, sr, "SRCLK", "SCK5", "input", stub=7.62)
    s.connect(sr, "~{SRCLR}", "VDD5", rotate=True)       # sideways: rows above/below are occupied
    hier(s, sr, "RCLK", "RCLK5", "input", stub=7.62)
    hier(s, sr, "~{OE}", "OE5_N", "input", stub=7.62)
    q_nets = ["ADDR1_0", "ADDR1_1", "ADDR1_2", "ADDR2_0", "ADDR2_1", "ADDR2_2", "EN2_N", "BIAS"]
    for q, n in zip(["QA", "QB", "QC", "QD", "QE", "QF", "QG", "QH"], q_nets):
        s.connect(sr, q, n)
    x, y = sr.pos("QH'")
    s.wire(x, y, x + 15.24, y)
    tap_tp(s, x + 10.16, y, "CTRL_OUT")
    s.label("CTRL_OUT", x + 15.24, y, 0, kind="hier", shape="output")
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
    x, y = m2.pos("S6")                                    # STIM_CAL: mid-supply calibration input
    s.wire(x, y, x + 12.7, y)
    pull(s, x + 12.7, y, "VDD5", "100k")
    pull(s, x + 12.7, y, "GND", "100k", up=False)
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
    # fixture ID interface: ESD + series R on every line that reaches the adapter
    XI = 340.36
    s.text("Fixture ID lines: ESD diode at the connector side, then series R.\n"
           "Not rated for the 24 V node fault (D14).", XI - 15.24, 15.24)
    for i, (ext, net, shape, rv, pu) in enumerate([
            ("PRESENT_N_EXT", "PRESENT_N", "output", "1k", True),
            ("ID_SDA_EXT", "ID_SDA", "bidirectional", "220", False),
            ("ID_SCL_EXT", "ID_SCL", "bidirectional", "220", False),
            ("ID_WP_EXT", "ID_WP", "input", "1k", False),
            ("ID_A0_EXT", "ID_A0", "input", "1k", False)]):
        id_line(s, XI, 43.18 + 20.32 * i, ext, net, shape, rv, pullup=pu)
    # ID_VCC: +3V3 -> current limit (survives a dead short: 33 mA, 0.11 W) -> ESD + decoupling -> connector
    y = 43.18 + 20.32 * 5 + U
    s.wire(XI - 12.7, y, XI - 8.89, y)
    s.wire(XI - 1.27, y, XI + 30.48, y)
    tap_power(s, "+3V3", XI - 12.7, y)
    rid = R(s, (XI - 5.08, y), "100", rot=90, fp=FP_R1206, fields={"Note": "ID_VCC current limit, dead-short rated"})
    rid.pin("1")
    rid.pin("2")
    tvs = s.add("Device:D_TVS", "D", (XI + 10.16, y + U + 3.81), rot=90, value="ESD 5V",
                footprint="Diode_SMD:D_SOD-323", fields=ESD)
    s.path((XI + 10.16, y), tvs.pos("2"))
    s.connect(tvs, "1", "GND")
    cap_down(s, XI + 22.86, y, "100n")
    s.label("ID_VCC_EXT", XI + 30.48, y, 0)
    # test points on the control-register outputs
    for k, n in enumerate(q_nets):
        y = 177.8 + 7.62 * k
        s.label(n, XI, y, 180)
        s.wire(XI, y, XI + 7.62, y)
        tap_tp(s, XI + 7.62, y, n)
    s.unused_nc()
    return s


# ------------------------------------------------------------------------------------------- control
CTRL_IN_PINS = ["SCK", "MOSI", "MISO", "RCLK", "PL_N", "OE_N", "BIAS_EN_N", "STIM_DRV", "STIM_EN_N", "ADC_STIM",
                "ADC_VDD5"]
CTRL_PINS = ([(n, "output" if n in ("MISO", "ADC_STIM", "ADC_VDD5") else "input", "L") for n in CTRL_IN_PINS] +
             [("MOSI5", "output", "R"), (None, None, "R"), ("STIM", "passive", "R"), ("SCK5", "output", "R"),
              ("RCLK5", "output", "R"), ("PL5_N", "output", "R"), ("OE5_N", "output", "R"),
              ("BIAS_EN5_N", "output", "R"), (None, None, "R"), ("SENSE_LAST", "input", "R")])


def unit_pins(unit):
    """(A, ~OE, Y) pin numbers of a 74xx125 unit."""
    return {1: ("2", "1", "3"), 2: ("5", "4", "6"), 3: ("9", "10", "8"), 4: ("12", "13", "11")}[unit.unit]


def build_control():
    s = Sheet("control", "control.kicad_sch", PRJ, "Proto40 - level shifting, stimulus driver, ADC taps")
    s.text("MCU (3.3 V) -> 5 V logic: 74AHCT125 (TTL input levels).   5 V sense chain -> MCU: 74LVC1G125 at 3.3 V.\n"
           "Pull-ups keep OE5_N, BIAS_EN and STIM_EN inactive while the MCU is in reset (review F6); pull-downs keep\n"
           "SCK and RCLK from clocking the chain while the MCU pins float.", 25.4, 12.7)
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
            elif src in ("SCK", "RCLK"):
                pull(s, xa - 10.16, ya, "GND", "100k", up=False, fields={"Note": "no clock edges during MCU reset"})
            s.connect(unit, oe, "GND")
            hier(s, unit, yp, dst, "output", stub=15.24)
        s.connect(units[4], "GND", "GND")
        decap(s, units[4], "VCC", side=-1)
    # MISO return buffer (3.3 V)
    mb = s.add("74xGxx:74LVC1G125", "U", (83.82, 220.98), footprint=FP_SOT235, text="icright", fields={"MPN": "SN74LVC1G125DBVR", **TI})
    hier(s, mb, "2", "SENSE_LAST", "input", stub=10.16)
    x, y = mb.pos("1")
    s.path((x, y), (x, y - 5.08), (x + 25.4, y - 5.08))         # ~OE tied low, GND clear of the reference text
    tap_power(s, "GND", x + 25.4, y - 5.08)
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
              ("ADC_STIM", "PA0", "input"), ("ADC_VDD5", "PA1", "input"), (None, None, None), (None, None, None),
              ("ID_SDA", "PB7", "bidirectional"), ("ID_SCL", "PB6", "bidirectional"),     # rows 14-17 line up
              ("ID_WP_A", "PB12", "output"), ("PRESENT_A_N", "PB14", "input"),            # with SideA's pins
              ("ID_WP_B", "PB13", "output"), ("PRESENT_B_N", "PB15", "input")]
MCU_PINS = ([("USB_DP", "bidirectional", "L"), ("USB_DM", "bidirectional", "L")] +
            [(n, t, "R") for n, _, t in MCU_HIER_R])
MCU_LOCAL = {"PA2": "LED_PASS", "PA3": "LED_FAIL", "PA4": "LED_BUSY", "PA9": "UART_TX", "PA10": "UART_RX",
             "PA13": "SWDIO", "PA14": "SWCLK", "PA15": "BUZZER"}


def build_mcu():
    s = Sheet("mcu", "mcu.kicad_sch", PRJ, "Proto40 - STM32C071 controller, UI, debug")
    s.text("Alternate functions to confirm in STM32CubeMX: SPI1 PA5/6/7, I2C1 PB6/7, USB PA11/12, ADC PA0/1.",
           25.4, 12.7)
    u = s.add("MCU_ST_STM32C0:STM32C071C8Tx", "U", (139.7, 139.7),
              fields={"MPN": "STM32C071C8T6", "Manufacturer": "STMicroelectronics"})
    for net, pin, shape in MCU_HIER_R:
        if net and pin not in ("PB6", "PB7"):
            hier(s, u, pin, net, shape, stub=7.62)
    # I2C pull-ups stand on the bus lines, staggered so the SDA one clears the SCL line and its label
    for pin, net, x_pull, x_lbl in (("PB6", "ID_SCL", 25.4, 30.48), ("PB7", "ID_SDA", 43.18, 50.8)):
        x, y = u.pos(pin)
        s.wire(x, y, x + x_lbl, y)
        pull(s, x + x_pull, y, "+3V3", "4.7k")
        s.label(net, x + x_lbl, y, 0, kind="hier", shape="bidirectional")
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
    cap_down(s, x - 20.32, y, "100n", text="left")
    # start button
    x, y = u.pos("PC13")
    s.wire(x, y, x - 33.02, y)
    pull(s, x - 7.62, y, "+3V3", "10k", text="left")
    cap_down(s, x - 17.78, y, "100n", text="left")
    sw = s.add("Switch:SW_Push", "SW", (x - 38.1, y), value="START", footprint="Button_Switch_SMD:SW_SPST_TL3342",
               fields={"MPN": "TL3342F160QG", "Manufacturer": "E-Switch"})
    sw.pin("2")
    x1, y1 = sw.pos("1")
    s.path((x1, y1), (x1 - 2.54, y1), (x1 - 2.54, y1 + 2.54))
    s.power("GND", x1 - 2.54, y1 + 2.54, 270)
    # LEDs
    for i, (net, col, mpn) in enumerate([("LED_PASS", "green", "KT-0603G"), ("LED_FAIL", "red", "KT-0603R"),
                                         ("LED_BUSY", "yellow", "KT-0603Y")]):
        y = 35.56 + 22.86 * i                   # pitch keeps each LED's GND clear of the next row
        s.label(net, 241.3, y, 180)
        rl = R(s, (251.46, y), "1k", rot=90)
        s.path((241.3, y), rl.pos("1"))
        xl = rl.pos("2")[0] + 5.08
        led = s.add("Device:LED", "D", (xl, y + 3.81), rot=90, value=col, footprint="LED_SMD:LED_0603_1608Metric",
                    fields={"MPN": mpn, "Manufacturer": "Hubei KENTO Elec"})
        s.path(rl.pos("2"), led.pos("A"))
        s.connect(led, "K", "GND", stub=5.08)
    # buzzer
    bz = s.add("Device:Buzzer", "BZ", (256.54, 111.76), footprint="Buzzer_Beeper:Buzzer_12x9.5RM7.6",
               fields={"MPN": "TBD: passive piezo, 12 x 9.5 mm, 7.6 mm pitch", "Note": "GPIO PWM"})
    x, y = bz.pos("1")
    s.wire(x, y, x - 12.7, y)
    s.label("BUZZER", x - 12.7, y, 180)
    x, y = bz.pos("2")
    s.path((x, y), (x - 5.08, y), (x - 5.08, y + 2.54))
    s.power("GND", x - 5.08, y + 2.54, 270)
    # SWD
    swd = s.add("Connector:Conn_ARM_SWD_TagConnect_TC2030", "J", (251.46, 139.7),
                footprint="Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical", text="icright",
                fields={"MPN": "none (Tag-Connect pads, cable TC2030-IDC-NL)", "LCSC": "none"})
    s.connect(swd, "VCC", "+3V3")
    s.connect(swd, "GND", "GND")
    s.nets(swd, {"SWDIO": "SWDIO", "SWCLK": "SWCLK", "~{RESET}": "NRST", "SWO": None})
    # UART
    uart = s.add("Connector_Generic:Conn_01x03", "J", (264.16, 180.34), value="UART",
                 footprint="Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", text="icright",
                 fields={"MPN": "TBD: 1x03 2.54 mm pin header"})
    s.connect(uart, "1", "UART_TX", stub=7.62)
    s.connect(uart, "2", "UART_RX", stub=7.62)
    x, y = uart.pos("3")
    s.path((x, y), (x - 2.54, y), (x - 2.54, y + 2.54))
    s.power("GND", x - 2.54, y + 2.54, 270)
    s.unused_nc()
    return s


# ------------------------------------------------------------------------------------------- power
def build_power():
    s = Sheet("power", "power.kicad_sch", PRJ, "Proto40 - USB-C power, VDD5 shunt clamp, 3.3 V")
    s.text("VBUS -> PTC -> LM66100 ideal diode (never back-feeds the host) -> ferrite -> VDD5.\n"
           "TL431 + BCP53 shunt clamp holds VDD5 <= 5.45 V when fixture faults inject current (review F9).",
           25.4, 12.7)
    j = s.add("Connector:USB_C_Receptacle_USB2.0_16P", "J", (40.64, 124.46), text="icright",
              footprint="Connector_USB:USB_C_Receptacle_HCTL_HC-TYPE-C-16P-01A",
              fields={"MPN": "HC-TYPE-C-16P-01A", "Manufacturer": "HCTL"})
    for pin in ("A9", "B4", "B9", "A12", "B1", "B12"):
        j.pin(pin)
    s.connect(j, "A8", None)
    s.connect(j, "B8", None)
    s.connect(j, "A1", "GND")
    # D+/D- pairs joined, then through the ESD array
    (xa7, ya7), (xb7, yb7) = j.pos("A7"), j.pos("B7")
    (xa6, ya6), (xb6, yb6) = j.pos("A6"), j.pos("B6")
    s.path((xa7, ya7), (xa7 + 5.08, ya7), (xa7 + 5.08, yb7), (xb7, yb7))
    s.path((xa6, ya6), (xa6 + 2.54, ya6), (xa6 + 2.54, yb6), (xb6, yb6))
    esd = s.add("Power_Protection:USBLC6-2SC6", "U", (106.68, 124.46),
                fields={"MPN": "USBLC6-2SC6", "Manufacturer": "STMicroelectronics"})
    s.path((xa7 + 5.08, ya7), (xa7 + 20.32, ya7), (xa7 + 20.32, esd.pos("1")[1]), esd.pos("1"))
    s.path((xa6 + 2.54, yb6), (xa6 + 22.86, yb6), (xa6 + 22.86, esd.pos("3")[1]), esd.pos("3"))
    hier(s, esd, "6", "USB_DM", "bidirectional", stub=10.16)
    hier(s, esd, "4", "USB_DP", "bidirectional", stub=10.16)
    s.connect(esd, "2", "GND")
    # CC pull-downs (Rd = 5.1k, sink role), wired up from the CC pins into the space below the VBUS line
    for pin, x_up, y_r in (("A5", 73.66, 96.52), ("B5", 76.2, 109.22)):
        xp, yp = j.pos(pin)
        rd = R(s, (x_up + 7.62, y_r), "5.1k", rot=90, fields={"Note": "USB-C Rd"})
        s.path((xp, yp), (x_up, yp), (x_up, y_r), rd.pos("1"))
        s.wire(*rd.pos("2"), x_up + 15.24, y_r)
        tap_power(s, "GND", x_up + 15.24, y_r)
    # shield
    xs, ys = j.pos("SH")
    s.wire(xs, ys, xs, ys + 5.08)
    s.wire(xs, ys + 5.08, xs - 12.7, ys + 5.08)
    rsh = r_down(s, xs - 5.08, ys + 5.08, "1M", text="right")
    s.connect(rsh, "2", "GND")
    cap_down(s, xs - 12.7, ys + 5.08, "4.7n", text="left", fields={"Note": ">= 100 V"})
    # VBUS → PTC → ideal diode → ferrite → VDD5
    yv = 78.74
    xv, yvb = j.pos("A4")
    s.path((xv, yvb), (xv + 7.62, yvb), (xv + 7.62, yv))
    s.power("VBUS", xv + 7.62, yv, 90)
    tap_flag(s, xv + 20.32, yv)
    f = s.add("Device:Polyfuse", "F", (91.44, yv), rot=90, value="500mA", footprint="Fuse:Fuse_1206_3216Metric",
              fields={"MPN": "1206L050YR", "Manufacturer": "Littelfuse", "Note": "500 mA hold, 6 V"})
    s.path((xv + 7.62, yv), f.pos("1"))
    idd = s.add("Power_Management:LM66100DCK", "U", (139.7, yv + 2.54), text="icright",
                fields={"MPN": "LM66100DCKR", **TI})
    s.path(f.pos("2"), idd.pos("VIN"))
    xf2 = f.pos("2")[0]
    tap_flag(s, xf2 + 6.35, yv)
    s.wire(xf2 + 16.51, yv, xf2 + 16.51, yv - 5.08)
    s.label("VBUS_F", xf2 + 16.51, yv - 5.08, 90)                 # net name (POWER net class)
    xe5, ye5 = esd.pos("5")
    s.wire(xe5, ye5, xe5, yv)                                       # ESD VBUS reference on VBUS_F
    cap_down(s, xf2 + 22.86, yv, "10u", fp=FP_C0805, text="left")
    x, y = idd.pos("~{CE}")
    s.path((x, y), (x - 2.54, y), (x - 2.54, y + 7.62))
    s.power("GND", x - 2.54, y + 7.62, 270)
    s.connect(idd, "GND", "GND")
    s.connect(idd, "ST", None)
    fb = s.add("Device:FerriteBead", "FB", (157.48, yv), rot=90, value="600R@100MHz", text="below",
               footprint="Inductor_SMD:L_0603_1608Metric",
               fields={"MPN": "BLM18KG601SN1D", "Manufacturer": "Murata", "Note": ">= 1 A"})
    s.path(idd.pos("VOUT"), fb.pos("1"))
    xr0 = fb.pos("2")[0]
    tap_power(s, "VDD5", xr0 + 12.7, yv)
    tap_flag(s, xr0 + 22.86, yv)
    for i, v in enumerate(["10u", "10u", "100n"]):
        cap_down(s, xr0 + 27.94 + 12.7 * i, yv, v, fp=FP_C0805 if v == "10u" else FP_C0603)
    tap_tp(s, xr0 + 63.5, yv, "VDD5")
    # shunt clamp: PNP on VDD5, TL431 sets ~5.45 V
    q = s.add("Transistor_BJT:BCP53", "Q", (xr0 + 80.01, 93.98), rot=180, text="left",
              fields={"MPN": "BCP53-16", "Manufacturer": "Nexperia",
                      "Note": "shunt pass, up to ~1 W at 300 mA: >= 1 cm2 collector copper"})
    xe, ye = q.pos("E")
    s.wire(xe, ye, xe, yv)
    xc, yc = q.pos("2")
    x4, y4 = q.pos("4")                                             # tab = collector: own stub, joins pin 2
    s.path((x4, y4), (x4, y4 + U), (xc, y4 + U))
    s.wire(xc, yc, xc, yc + 5.08)
    rce = R(s, (xc, yc + 5.08 + 3.81), "6.8", fp=FP_R2512, text="left",
            fields={"Note": "collector ballast, 0.6 W at 300 mA (1 W part)"})
    rce.pin("1")
    s.connect(rce, "2", "GND")
    xb, yb = q.pos("B")
    XN = xb + 7.62
    rbe = r_down(s, XN, yv, "10k")
    s.path(rbe.pos("2"), (XN, yb), (xb, yb))
    XT = XN + 12.7
    s.path((XN, yb), (XN, yb + 2.54), (XT, yb + 2.54))
    rbk = R(s, (XT, yb + 6.35), "470")
    rbk.pin("1")
    tl = s.add("Reference_Voltage:TL431DBZ", "U", (XT, yb + 15.24), rot=90, fields={"MPN": "TL431BIDBZR", **TI})
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
                fields={"MPN": "AP2112K-3.3TRG1", "Manufacturer": "Diodes Incorporated"})
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
    tp2 = s.add("Connector:TestPoint", "TP", (xo + 27.94, yo - U), value="+3V3", footprint=FP_TP, text="right",
                fields=NO_PART)
    s.path((xo + 27.94, yo), tp2.pos("1"))
    tp3 = s.add("Connector:TestPoint", "TP", (241.3, 190.5), value="GND", footprint=FP_TP, text="right",
                fields=NO_PART)
    s.connect(tp3, "1", "GND")
    fg = s.add("power:PWR_FLAG", "#FLG", (63.5, 154.94))
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
    m = root.sheet("MCU", mcu, (71.12, TOP), (38.1, U * 20), MCU_PINS)
    cs = root.sheet("Control", ctrl, (160.02, TOP), (33.02, U * 12), CTRL_PINS)
    sa = root.sheet("SideA", side, (251.46, TOP), (35.56, U * 18), SIDE_PINS)
    sb = root.sheet("SideB", side, (251.46, TOP + 63.5), (35.56, U * 18), SIDE_PINS)
    for n in ("USB_DP", "USB_DM"):
        root.path(p.pin(n)[:2], m.pin(n)[:2])
    for n in CTRL_IN_PINS:
        root.path(m.pin(n)[:2], cs.pin(n)[:2])
    # control -> both sides: shared nets as rails
    shared = [("STIM", "STIM"), ("SCK5", "SCK5"), ("RCLK5", "RCLK5"), ("PL5_N", "PL5_N"), ("OE5_N", "OE5_N"),
              ("BIAS_EN5_N", "BIAS_EN_N")]
    for i, (cp, sp) in enumerate(shared):
        x = 210.82 + 5.08 * i                       # first rail clear of the SENSE_LAST label
        yc = cs.pin(cp)[1]
        root.path(cs.pin(cp)[:2], (x, yc))
        root.path((x, yc), sa.pin(sp)[:2])
        root.path((x, yc), (x, sb.pin(sp)[1]), sb.pin(sp)[:2])
    root.path(cs.pin("MOSI5")[:2], sa.pin("CTRL_IN")[:2])
    root.connect(sa, "SENSE_IN", "GND", rotate=True, stub=5.08)   # chain start; sideways: dense pin column
    root.connect(sa, "ID_A0", "GND", rotate=True, stub=5.08)      # EEPROM address strap A0 = 0
    root.connect(sb, "ID_A0", "+3V3", rotate=True, stub=5.08)     # A0 = 1
    # daisy chains SideA -> SideB, routed around the right of SideA
    for out, inp, x_r, y_m, x_l in (("CTRL_OUT", "CTRL_IN", 297.18, 101.6, 248.92),
                                    ("SENSE_OUT", "SENSE_IN", 294.64, 99.06, 246.38)):
        (x0, y0), (x1, y1) = sa.pin(out)[:2], sb.pin(inp)[:2]
        root.path((x0, y0), (x_r, y0), (x_r, y_m), (x_l, y_m), (x_l, y1), (x1, y1))
    root.connect(sb, "CTRL_OUT", None)
    # the chain end returns to the MISO buffer on Control: a label, the path would cross every rail
    root.connect(sb, "SENSE_OUT", "SENSE_LAST")
    root.connect(cs, "SENSE_LAST", "SENSE_LAST")
    # fixture ID: SideA lines straight from the MCU, I2C bus continues as rails to SideB
    for n_m, n_s in (("ID_SDA", "ID_SDA"), ("ID_SCL", "ID_SCL"), ("ID_WP_A", "ID_WP"),
                     ("PRESENT_A_N", "PRESENT_N")):
        root.path(m.pin(n_m)[:2], sa.pin(n_s)[:2])
    for n_m, n_s, x, tap in (("ID_SDA", "ID_SDA", 203.2, True), ("ID_SCL", "ID_SCL", 200.66, True),
                             ("ID_WP_B", "ID_WP", 198.12, False), ("PRESENT_B_N", "PRESENT_N", 195.58, False)):
        (x0, y0), (x1, y1) = m.pin(n_m)[:2], sb.pin(n_s)[:2]
        start = (x, y0) if tap else (x0, y0)        # SDA/SCL tap the SideA line; WP_B/PRESENT_B start at the MCU
        root.path(start, (x, y0), (x, y1), (x1, y1))
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
