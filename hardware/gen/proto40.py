#!/usr/bin/env python3
"""Proto40 schematic: controller + 2 bank sides × (40 fixture nodes + shell + internal test nodes).

Generates hardware/proto40/*.kicad_sch. Edit this file, not the generated schematics.
Run: python3 proto40.py [output_dir]      (KICAD_SYMBOL_DIR = KiCad 10 symbol library directory)

Architecture: docs/design-review-and-kicad-plan.md (F1–F10), fixture pinout: docs/fixture-interface.md,
analog values: hardware/sim/report.md (Rs 4.7 kΩ 1206, Rbias 680 kΩ).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schgen import Project, Sheet

PRJ = "proto40"
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "proto40")

# ------------------------------------------------------------------------------------------- parts
FP_R0603 = "Resistor_SMD:R_0603_1608Metric"
FP_R1206 = "Resistor_SMD:R_1206_3216Metric"
FP_C0603 = "Capacitor_SMD:C_0603_1608Metric"
FP_C0805 = "Capacitor_SMD:C_0805_2012Metric"
FP_TSSOP16 = "Package_SO:TSSOP-16_4.4x5mm_P0.65mm"
FP_TSSOP14 = "Package_SO:TSSOP-14_4.4x5mm_P0.65mm"
FP_SOT235 = "Package_TO_SOT_SMD:SOT-23-5"
FP_TP = "TestPoint:TestPoint_Pad_D1.0mm"

RS = dict(value="4.7k", footprint=FP_R1206, fields={"MPN": "1206 4.7 kΩ 1 % 0.25 W", "Note": "Rs, fault-rated, see sim"})
RB = dict(value="680k", footprint=FP_R0603, fields={"MPN": "0603 680 kΩ 1 %", "Note": "Rbias, see sim"})
TVS = dict(value="TVS 28V bidir", footprint="Diode_SMD:D_SOD-323",
           fields={"MPN": "TBD: bidirectional, VRWM >= 28 V, IR <= 100 nA @ 5 V, SOD-323"})


def r(sheet, at, value, rot=0, fp=FP_R0603, **kw):
    return sheet.add("Device:R", "R", at, rot=rot, value=value, footprint=fp, **kw)


def c(sheet, at, value="100n", rot=0, fp=FP_C0603, **kw):
    return sheet.add("Device:C", "C", at, rot=rot, value=value, footprint=fp, **kw)


def decouple(sheet, at, rail="VDD5", value="100n", fp=FP_C0603):
    cap = c(sheet, at, value, fp=fp)
    sheet.connect(cap, "1", rail)
    sheet.connect(cap, "2", "GND")
    return cap


def two_pin(sheet, part, a, b, **kw):
    sheet.connect(part, "1", a, **kw)
    sheet.connect(part, "2", b, **kw)


# ------------------------------------------------------------------------------------------- group8
def build_group8():
    """8 symmetric channel cells + 1st-stage 8:1 mux + '165 sense register."""
    s = Sheet("group8", "group8.kicad_sch", PRJ, "Proto40 – 8-channel group")
    H = dict(kind="hier")
    s.text("8 symmetric channel cells: EXT → TVS / Rs 4.7 kΩ → NODE → Rbias 680 kΩ → BIAS_RAIL.\n"
           "NODE feeds the 1st-stage mux (drive/ADC path) and the '165 (sense). C (DNP) = optional filter.",
           25, 15)
    for k in range(8):
        y = 35 + k * 27
        ext, node = f"EXT{k}", f"NODE{k}"
        tvs = s.add("Device:D_TVS", "D", (40, y + 8), rot=90, **TVS)
        s.connect(tvs, "2", ext, shape="passive", **H)
        s.connect(tvs, "1", "GND")
        rs = r(s, (70, y), RS["value"], rot=90, fp=RS["footprint"], fields=RS["fields"])
        s.connect(rs, "1", ext, shape="passive", **H)
        s.connect(rs, "2", node)
        rb = r(s, (100, y + 8), RB["value"], fp=RB["footprint"], fields=RB["fields"])
        s.connect(rb, "1", node)
        s.connect(rb, "2", "BIAS_RAIL", shape="passive", **H)
        cf = c(s, (120, y + 8), "100p", dnp=True)
        s.connect(cf, "1", node)
        s.connect(cf, "2", "GND")
    mux = s.add("cable_tester:TMUX1308", "U", (200, 120), footprint=FP_TSSOP16)
    s.nets(mux, {f"S{k}": f"NODE{k}" for k in range(8)})
    s.connect(mux, "D", "MUXOUT", shape="passive", **H)
    for k in range(3):
        s.connect(mux, f"SEL{k}", f"ADDR{k}", shape="input", **H)
    s.connect(mux, "~{E}", "EN_N", shape="input", **H)
    s.nets(mux, {"VDD": "VDD5", "GND": "GND"})
    sr = s.add("74xx:74HC165", "U", (300, 120), footprint=FP_TSSOP16,
               fields={"MPN": "SN74HC165PWR", "Manufacturer": "Texas Instruments"})
    s.nets(sr, {f"D{k}": f"NODE{k}" for k in range(8)})
    s.connect(sr, "DS", "SER_IN", shape="input", **H)
    s.connect(sr, "Q7", "SER_OUT", shape="output", **H)
    s.connect(sr, "~{Q7}", None)
    s.connect(sr, "CP", "CLK", shape="input", **H)
    s.connect(sr, "~{PL}", "PL_N", shape="input", **H)
    s.nets(sr, {"~{CE}": "GND", "VCC": "VDD5", "GND": "GND"})
    decouple(s, (200, 175))
    decouple(s, (300, 175))
    s.unused_nc()
    return s


G8_PINS = ([(f"EXT{k}", "passive", "L") for k in range(8)] + [("BIAS_RAIL", "passive", "L")] +
           [("ADDR0", "input", "R"), ("ADDR1", "input", "R"), ("ADDR2", "input", "R"), ("EN_N", "input", "R"),
            ("CLK", "input", "R"), ("PL_N", "input", "R"), ("SER_IN", "input", "R"), ("SER_OUT", "output", "R"),
            ("MUXOUT", "passive", "R")])


# ------------------------------------------------------------------------------------------- side
DIN_FIXED = {"a1": "GND", "a27": "GND", "a28": "SHELL", "a29": "ID_SDA", "a30": "ID_SCL", "a31": "ID_VCC",
             "a32": "GND", "c1": "GND", "c27": "GND", "c28": "PRESENT_N", "c29": "ID_WP", "c30": "ID_A0",
             "c31": "GND", "c32": "GND"}
POPULATED = 40


def din_net(pin):
    if pin in DIN_FIXED:
        return DIN_FIXED[pin]
    row, n = pin[0], int(pin[1:])
    ch = n - 1 if row == "a" else 25 + n - 1
    return f"EXT{ch:02d}" if ch <= POPULATED else None


def build_side(group8):
    s = Sheet("side", "side.kicad_sch", PRJ, "Proto40 – bank side (fixture connector, 6 groups, 2nd-stage mux)")
    H = dict(kind="hier")
    s.text("Fixture connector: docs/fixture-interface.md. EXT41–EXT50 not populated on Proto40.\n"
           "Group 6 = internal nodes: SHELL, LOOP (to other side), OPEN (known open), RREF (100 kΩ to GND).", 20, 12)
    j = s.add("Connector:DIN41612_02x32_AC", "J", (45, 150),
              footprint="Connector_DIN:DIN41612_C_2x32_Female_Vertical_THT",
              fields={"MPN": "DIN 41612 type C 2x32 female vertical, performance level 1/2"})
    for row in "ac":
        for n in range(1, 33):
            pin = f"{row}{n}"
            net = din_net(pin)
            if net in ("ID_SDA", "ID_SCL", "ID_WP", "PRESENT_N", "ID_A0"):
                s.connect(j, pin, net, shape="bidirectional" if net.startswith("ID_S") else "input", **H)
            else:
                s.connect(j, pin, net)
    # 6 groups
    groups = []
    for g in range(6):
        gy = 22 + g * 40
        sh = s.sheet(f"G{g + 1}", group8, (130, gy), (45, 2.54 * 10), G8_PINS)
        groups.append(sh)
        for k in range(8):
            if g < 5:
                net = f"EXT{g * 8 + k + 1:02d}"
            else:
                net = {0: "SHELL", 1: "LOOP", 3: "RREF"}.get(k)
            if net == "LOOP":
                s.connect(sh, f"EXT{k}", "LOOP", shape="passive", **H)
            else:
                s.connect(sh, f"EXT{k}", net)
        s.connect(sh, "BIAS_RAIL", "BIAS_RAIL")
        for k in range(3):
            s.connect(sh, f"ADDR{k}", f"ADDR1_{k}")
        s.nets(sh, {"EN_N": "EN2_N", "CLK": "SCK5", "MUXOUT": f"MUX{g + 1}"})
        s.connect(sh, "PL_N", "PL5_N", **(dict(shape="input", **H) if g == 0 else {}))
        if g == 0:
            s.connect(sh, "SER_IN", "SENSE_IN", shape="input", **H)
        else:
            s.connect(sh, "SER_IN", f"SCH{g}")
        if g == 5:
            s.connect(sh, "SER_OUT", "SENSE_OUT", shape="output", **H)
        else:
            s.connect(sh, "SER_OUT", f"SCH{g + 1}")
    # RREF
    rref = r(s, (215, 250), "100k", fields={"Note": "load-signature reference node"})
    two_pin(s, rref, "RREF", "GND")
    # 2nd-stage mux
    m2 = s.add("cable_tester:TMUX1308", "U", (290, 60), footprint=FP_TSSOP16)
    s.nets(m2, {f"S{g}": f"MUX{g + 1}" for g in range(6)})
    s.connect(m2, "S6", "STIM_CAL")
    s.connect(m2, "S7", None)
    s.connect(m2, "D", "STIM", shape="passive", **H)
    for k in range(3):
        s.connect(m2, f"SEL{k}", f"ADDR2_{k}")
    s.nets(m2, {"~{E}": "EN2_N", "VDD": "VDD5", "GND": "GND"})
    decouple(s, (320, 40))
    rc1 = r(s, (330, 75), "100k")
    two_pin(s, rc1, "VDD5", "STIM_CAL")
    rc2 = r(s, (345, 75), "100k")
    two_pin(s, rc2, "STIM_CAL", "GND")
    # control register
    sr = s.add("74xx:74HC595", "U", (290, 150), footprint=FP_TSSOP16,
               fields={"MPN": "SN74HC595PWR", "Manufacturer": "Texas Instruments"})
    outs = ["ADDR1_0", "ADDR1_1", "ADDR1_2", "ADDR2_0", "ADDR2_1", "ADDR2_2", "EN2_N", "BIAS"]
    s.nets(sr, {q: n for q, n in zip(["QA", "QB", "QC", "QD", "QE", "QF", "QG", "QH"], outs)})
    s.connect(sr, "SER", "CTRL_IN", shape="input", **H)
    s.connect(sr, "QH'", "CTRL_OUT", shape="output", **H)
    s.connect(sr, "SRCLK", "SCK5", shape="input", **H)
    s.connect(sr, "RCLK", "RCLK5", shape="input", **H)
    s.connect(sr, "~{OE}", "OE5_N", shape="input", **H)
    s.nets(sr, {"~{SRCLR}": "VDD5", "VCC": "VDD5", "GND": "GND"})
    decouple(s, (320, 125))
    pu = r(s, (330, 175), "100k", fields={"Note": "mux disabled while 595 outputs are Hi-Z"})
    two_pin(s, pu, "VDD5", "EN2_N")
    pd = r(s, (345, 175), "100k", fields={"Note": "bias low while 595 outputs are Hi-Z"})
    two_pin(s, pd, "BIAS", "GND")
    # bias rail driver
    bd = s.add("74xGxx:74AHCT1G125", "U", (290, 225), footprint=FP_SOT235,
               fields={"MPN": "SN74AHCT1G125DBVR", "Manufacturer": "Texas Instruments"})
    s.connect(bd, "2", "BIAS")
    s.connect(bd, "1", "BIAS_EN_N", shape="input", **H)
    s.connect(bd, "4", "BIAS_RAIL")
    s.nets(bd, {"VCC": "VDD5", "GND": "GND"})
    decouple(s, (320, 210))
    pb = r(s, (330, 250), "100k", fields={"Note": "bias Hi-Z until MCU enables"})
    s.connect(pb, "1", "VDD5")
    s.connect(pb, "2", "BIAS_EN_N", shape="input", **H)
    tp = s.add("Connector:TestPoint", "TP", (360, 230), value="BIAS_RAIL", footprint=FP_TP)
    s.connect(tp, "1", "BIAS_RAIL")
    # ID power and presence
    rid = r(s, (215, 220), "47", fields={"Note": "ID_VCC current limit"})
    two_pin(s, rid, "+3V3", "ID_VCC")
    cid = c(s, (230, 220), "100n")
    two_pin(s, cid, "ID_VCC", "GND")
    ppu = r(s, (245, 220), "10k")
    s.connect(ppu, "1", "+3V3")
    s.connect(ppu, "2", "PRESENT_N", shape="input", **H)
    decouple(s, (380, 125), value="10u", fp=FP_C0805)
    s.unused_nc()
    return s


SIDE_PINS = ([("STIM", "passive", "L"), ("SCK5", "input", "L"), ("RCLK5", "input", "L"), ("PL5_N", "input", "L"),
              ("OE5_N", "input", "L"), ("BIAS_EN_N", "input", "L"), ("CTRL_IN", "input", "L"),
              ("SENSE_IN", "input", "L"), ("ID_A0", "input", "L")] +
             [("CTRL_OUT", "output", "R"), ("SENSE_OUT", "output", "R"), ("ID_SDA", "bidirectional", "R"),
              ("ID_SCL", "bidirectional", "R"), ("ID_WP", "input", "R"), ("PRESENT_N", "input", "R"),
              ("LOOP", "passive", "R")])


# ------------------------------------------------------------------------------------------- control
def build_control():
    s = Sheet("control", "control.kicad_sch", PRJ, "Proto40 – level shifting, stimulus driver, ADC taps")
    H = dict(kind="hier")
    s.text("3.3 V MCU → 5 V logic: 74AHCT125 (TTL inputs). 5 V chain → MCU: 74LVC1G125 at 3.3 V.\n"
           "STIM: 74AHCT1G125 → 150 Ω → STIM bus. ADC taps: 100k/100k dividers (review F4, F8).", 20, 12)
    b1 = [s.add("74xx:74AHCT125", "U", (80, 50), unit=1, footprint=FP_TSSOP14,
                fields={"MPN": "SN74AHCT125PWR", "Manufacturer": "Texas Instruments"})]
    for u in range(1, 5):
        b1.append(s.add("74xx:74AHCT125", "U", (80, 50 + 30 * u), unit=u + 1, footprint=FP_TSSOP14,
                        same_as=b1[0], fields={"MPN": "SN74AHCT125PWR"}))
    pairs = [("SCK", "SCK5"), ("MOSI", "MOSI5"), ("RCLK", "RCLK5"), ("PL_N", "PL5_N")]
    pins = [("2", "1", "3"), ("5", "4", "6"), ("9", "10", "8"), ("12", "13", "11")]
    for (a, oe, y), (src, dst), unit in zip(pins, pairs, b1):
        s.connect(unit, a, src, shape="input", **H)
        s.connect(unit, oe, "GND")
        s.connect(unit, y, dst, shape="output", **H)
    s.nets(b1[4], {"VCC": "VDD5", "GND": "GND"})
    b2 = [s.add("74xx:74AHCT125", "U", (180, 50), unit=1, footprint=FP_TSSOP14,
                fields={"MPN": "SN74AHCT125PWR", "Manufacturer": "Texas Instruments"})]
    for u in range(1, 5):
        b2.append(s.add("74xx:74AHCT125", "U", (180, 50 + 30 * u), unit=u + 1, footprint=FP_TSSOP14,
                        same_as=b2[0], fields={"MPN": "SN74AHCT125PWR"}))
    for (a, oe, y), (src, dst), unit in zip(pins[:2], [("OE_N", "OE5_N"), ("BIAS_EN_N", "BIAS_EN5_N")], b2):
        s.connect(unit, a, src, shape="input", **H)
        s.connect(unit, oe, "GND")
        s.connect(unit, y, dst, shape="output", **H)
    for (a, oe, y), unit in zip(pins[2:], b2[2:4]):
        s.connect(unit, a, "GND")
        s.connect(unit, oe, "VDD5")
        s.connect(unit, y, None)
    s.nets(b2[4], {"VCC": "VDD5", "GND": "GND"})
    for i, net in enumerate(["OE_N", "BIAS_EN_N", "STIM_EN_N"]):
        pu = r(s, (240 + 15 * i, 40), "10k", fields={"Note": "safe default during MCU reset"})
        s.connect(pu, "1", "+3V3")
        s.connect(pu, "2", net, shape="input", **H)
    # MISO return
    mb = s.add("74xGxx:74LVC1G125", "U", (80, 230), footprint=FP_SOT235,
               fields={"MPN": "SN74LVC1G125DBVR", "Manufacturer": "Texas Instruments"})
    s.connect(mb, "2", "SENSE_LAST", shape="input", **H)
    s.connect(mb, "1", "GND")
    s.connect(mb, "4", "MISO", shape="output", **H)
    s.nets(mb, {"VCC": "+3V3", "GND": "GND"})
    # stimulus driver
    sd = s.add("74xGxx:74AHCT1G125", "U", (180, 200), footprint=FP_SOT235,
               fields={"MPN": "SN74AHCT1G125DBVR", "Manufacturer": "Texas Instruments"})
    s.connect(sd, "2", "STIM_DRV", shape="input", **H)
    s.connect(sd, "1", "STIM_EN_N", shape="input", **H)
    s.connect(sd, "4", "STIM_OUT")
    s.nets(sd, {"VCC": "VDD5", "GND": "GND"})
    rl = r(s, (230, 200), "150", rot=90, fields={"Note": "Rlim"})
    s.connect(rl, "1", "STIM_OUT")
    s.connect(rl, "2", "STIM", shape="passive", **H)
    tp = s.add("Connector:TestPoint", "TP", (260, 185), value="STIM", footprint=FP_TP)
    s.connect(tp, "1", "STIM", shape="passive", **H)
    # ADC dividers
    for i, (src, adc) in enumerate([("STIM", "ADC_STIM"), ("VDD5", "ADC_VDD5")]):
        x = 300 + 40 * i
        ra = r(s, (x, 200), "100k")
        if src == "STIM":
            s.connect(ra, "1", "STIM", shape="passive", **H)
        else:
            s.connect(ra, "1", "VDD5")
        s.connect(ra, "2", adc, shape="output", **H)
        rb = r(s, (x + 12, 230), "100k")
        s.connect(rb, "1", adc, shape="output", **H)
        s.connect(rb, "2", "GND")
        ca = c(s, (x + 24, 230), "1n")
        s.connect(ca, "1", adc, shape="output", **H)
        s.connect(ca, "2", "GND")
    for i in range(4):
        decouple(s, (250 + 15 * i, 120), "VDD5" if i < 3 else "+3V3")
    s.unused_nc()
    return s


CTRL_PINS = ([(n, "input", "L") for n in ["SCK", "MOSI", "RCLK", "PL_N", "OE_N", "BIAS_EN_N", "STIM_DRV",
                                           "STIM_EN_N"]] + [("MISO", "output", "L"), ("ADC_STIM", "output", "L"),
                                                            ("ADC_VDD5", "output", "L")] +
             [(n, "output", "R") for n in ["SCK5", "MOSI5", "RCLK5", "PL5_N", "OE5_N", "BIAS_EN5_N"]] +
             [("STIM", "passive", "R"), ("SENSE_LAST", "input", "R")])


# ------------------------------------------------------------------------------------------- mcu
MCU_MAP = {"PA0": "ADC_STIM", "PA1": "ADC_VDD5", "PA2": "LED_PASS", "PA3": "LED_FAIL", "PA4": "LED_BUSY",
           "PA5": "SCK", "PA6": "MISO", "PA7": "MOSI", "PA8": "STIM_DRV", "PA9": "UART_TX", "PA10": "UART_RX",
           "PA11": "USB_DM", "PA12": "USB_DP", "PA13": "SWDIO", "PA14": "SWCLK", "PA15": "BUZZER",
           "PB0": "RCLK", "PB1": "PL_N", "PB2": "OE_N", "PB3": "STIM_EN_N", "PB4": "BIAS_EN_N",
           "PB6": "ID_SCL", "PB7": "ID_SDA", "PB12": "ID_WP_A", "PB13": "ID_WP_B", "PB14": "PRESENT_A_N",
           "PB15": "PRESENT_B_N", "PC13": "START_N", "PF2": "NRST"}
MCU_HIER = {"ADC_STIM": "input", "ADC_VDD5": "input", "SCK": "output", "MISO": "input", "MOSI": "output",
            "STIM_DRV": "output", "USB_DM": "bidirectional", "USB_DP": "bidirectional", "RCLK": "output",
            "PL_N": "output", "OE_N": "output", "STIM_EN_N": "output", "BIAS_EN_N": "output",
            "ID_SCL": "bidirectional", "ID_SDA": "bidirectional", "ID_WP_A": "output", "ID_WP_B": "output",
            "PRESENT_A_N": "input", "PRESENT_B_N": "input"}


def build_mcu():
    s = Sheet("mcu", "mcu.kicad_sch", PRJ, "Proto40 – STM32C071 controller, USB, UI, debug")
    H = dict(kind="hier")
    s.text("Pin assignment to be confirmed with STM32CubeMX (AF mapping: SPI1 PA5/6/7, I2C1 PB6/7, USB PA11/12).",
           20, 12)
    u = s.add("MCU_ST_STM32C0:STM32C071C8Tx", "U", (150, 140),
              fields={"MPN": "STM32C071C8T6", "Manufacturer": "STMicroelectronics"})
    for pin, net in MCU_MAP.items():
        if net in MCU_HIER:
            s.connect(u, pin, net, shape=MCU_HIER[net], **H)
        else:
            s.connect(u, pin, net)
    s.nets(u, {"VDD": "+3V3", "VSS": "GND", "VREF+": "+3V3"})
    for i, v in enumerate(["100n", "100n", "4.7u"]):
        decouple(s, (60 + 15 * i, 40), "+3V3", v, FP_C0805 if v == "4.7u" else FP_C0603)
    cr = c(s, (60, 230), "100n")
    two_pin(s, cr, "NRST", "GND")
    # SWD (Tag-Connect) and UART header
    swd = s.add("Connector:Conn_ARM_SWD_TagConnect_TC2030", "J", (260, 60),
                footprint="Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical")
    s.nets(swd, {"VCC": "+3V3", "GND": "GND", "SWDIO": "SWDIO", "SWCLK": "SWCLK", "~{RESET}": "NRST", "SWO": None})
    uart = s.add("Connector_Generic:Conn_01x03", "J", (330, 60),
                 footprint="Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", value="UART")
    s.nets(uart, {"1": "UART_TX", "2": "UART_RX", "3": "GND"})
    # I2C pull-ups for fixture EEPROMs
    for i, net in enumerate(["ID_SDA", "ID_SCL"]):
        pu = r(s, (260 + 15 * i, 120), "4.7k")
        s.connect(pu, "1", "+3V3")
        s.connect(pu, "2", net, shape="bidirectional", **H)
    # UI
    for i, net in enumerate(["LED_PASS", "LED_FAIL", "LED_BUSY"]):
        x = 260 + 25 * i
        rl = r(s, (x, 170), "1k")
        s.connect(rl, "1", net)
        s.connect(rl, "2", f"{net}_K")
        led = s.add("Device:LED", "D", (x, 195), rot=90, footprint="LED_SMD:LED_0603_1608Metric",
                    value={"LED_PASS": "green", "LED_FAIL": "red", "LED_BUSY": "yellow"}[net])
        s.connect(led, "2", f"{net}_K")
        s.connect(led, "1", "GND")
    bz = s.add("Device:Buzzer", "BZ", (350, 175), footprint="Buzzer_Beeper:Buzzer_12x9.5RM7.6",
               fields={"Note": "passive piezo, driven by GPIO PWM"})
    s.nets(bz, {"1": "BUZZER", "2": "GND"})
    sw = s.add("Switch:SW_Push", "SW", (280, 240), footprint="Button_Switch_SMD:SW_SPST_TL3342", value="START")
    s.nets(sw, {"1": "START_N", "2": "GND"})
    rp = r(s, (320, 235), "10k")
    two_pin(s, rp, "+3V3", "START_N")
    cs = c(s, (335, 235), "100n")
    two_pin(s, cs, "START_N", "GND")
    s.unused_nc()
    return s


MCU_PINS = ([(n, t, "R") for n, t in MCU_HIER.items() if n not in ("USB_DM", "USB_DP")] +
            [("USB_DM", "bidirectional", "L"), ("USB_DP", "bidirectional", "L")])


# ------------------------------------------------------------------------------------------- power
def build_power():
    s = Sheet("power", "power.kicad_sch", PRJ, "Proto40 – USB-C power, VDD5 shunt clamp, 3.3 V")
    H = dict(kind="hier")
    s.text("VBUS → polyfuse → LM66100 (reverse blocking, never back-feeds the host) → ferrite → VDD5.\n"
           "TL431 + BCP53 shunt clamp holds VDD5 ≤ 5.45 V when fixture faults inject current (review F9).", 20, 12)
    j = s.add("Connector:USB_C_Receptacle_USB2.0_16P", "J", (50, 90),
              footprint="Connector_USB:USB_C_Receptacle_HCTL_HC-TYPE-C-16P-01A")
    s.nets(j, {"A4": "VBUS", "A5": "CC1", "B5": "CC2", "A6": "USB_D+", "A7": "USB_D-", "A8": None, "B8": None,
               "A1": "GND", "SH": "USB_SHIELD"})
    for pin in ("A9", "B4", "B9"):
        j.pin(pin)
    for pin in ("A12", "B1", "B12"):
        j.pin(pin)
    s.connect(j, "B6", "USB_D+")
    s.connect(j, "B7", "USB_D-")
    flag = s.add("power:PWR_FLAG", "#FLG", (30, 120))
    for k, net in enumerate(["CC1", "CC2"]):
        rc = r(s, (100 + 15 * k, 70), "5.1k")
        two_pin(s, rc, net, "GND")
    rsh = r(s, (100, 130), "1M")
    two_pin(s, rsh, "USB_SHIELD", "GND")
    csh = c(s, (115, 130), "4.7n", fields={"Note": "shield to GND, ≥ 100 V"})
    two_pin(s, csh, "USB_SHIELD", "GND")
    esd = s.add("Power_Protection:USBLC6-2SC6", "U", (150, 100), fields={"MPN": "USBLC6-2SC6"})
    s.nets(esd, {"1": "USB_D+", "3": "USB_D-", "5": "VBUS_F", "2": "GND"})
    s.nets(esd, {"6": "USB_DP", "4": "USB_DM"}, shape="bidirectional", **H)
    pf = s.add("Device:Polyfuse", "F", (100, 180), footprint="Fuse:Fuse_1206_3216Metric", value="500mA",
               fields={"MPN": "1206 PTC 500 mA hold, 6 V"})
    two_pin(s, pf, "VBUS", "VBUS_F")
    idd = s.add("Power_Management:LM66100DCK", "U", (150, 180), fields={"MPN": "LM66100DCKR"})
    s.nets(idd, {"VIN": "VBUS_F", "~{CE}": "GND", "VOUT": "VDD5_RAW", "GND": "GND", "ST": None})
    fb = s.add("Device:FerriteBead", "FB", (200, 180), footprint="Inductor_SMD:L_0603_1608Metric",
               value="600R@100MHz", fields={"Note": "≥ 1 A"})
    s.connect(fb, "1", "VDD5_RAW")
    x, y, a = fb.pin("2")
    s.power("VDD5", x, y, 90)
    s.add("power:PWR_FLAG", "#FLG", (x, y))            # VDD5 is driven only through the ferrite
    for i, v in enumerate(["10u", "10u", "100n"]):
        decouple(s, (220 + 15 * i, 200), "VDD5", v, FP_C0805 if v != "100n" else FP_C0603)
    cin = c(s, (130, 200), "10u", fp=FP_C0805)
    two_pin(s, cin, "VBUS_F", "GND")
    # shunt clamp
    q = s.add("Transistor_BJT:BCP53", "Q", (300, 90), fields={"MPN": "BCP53-16", "Note": "shunt pass, ≥ 1 W"})
    s.nets(q, {"E": "VDD5", "B": "CLAMP_B"})
    s.connect(q, "2", "CLAMP_C")
    s.connect(q, "4", "CLAMP_C")
    rce = r(s, (330, 120), "4.7", fp=FP_R1206, fields={"Note": "collector ballast"})
    two_pin(s, rce, "CLAMP_C", "GND")
    rbe = r(s, (260, 70), "10k")
    two_pin(s, rbe, "VDD5", "CLAMP_B")
    rbk = r(s, (260, 110), "470")
    two_pin(s, rbk, "CLAMP_B", "CLAMP_K")
    tl = s.add("Reference_Voltage:TL431DBZ", "U", (290, 140), fields={"MPN": "TL431BIDBZR"})
    s.nets(tl, {"K": "CLAMP_K", "A": "GND", "REF": "CLAMP_REF"})
    rt = r(s, (340, 150), "11.8k", fields={"Note": "sets clamp at ≈ 5.45 V"})
    two_pin(s, rt, "VDD5", "CLAMP_REF")
    rbt = r(s, (355, 150), "10k")
    two_pin(s, rbt, "CLAMP_REF", "GND")
    # 3.3 V
    ldo = s.add("Regulator_Linear:AP2112K-3.3", "U", (300, 230), fields={"MPN": "AP2112K-3.3TRG1"})
    s.nets(ldo, {"VIN": "VDD5", "EN": "VDD5", "GND": "GND", "VOUT": "+3V3", "NC": None})
    decouple(s, (340, 240), "+3V3", "1u")
    decouple(s, (270, 250), "VDD5", "1u")
    # flags
    s.connect(flag, "1", "GND")
    fv = s.add("power:PWR_FLAG", "#FLG", (60, 160))
    s.connect(fv, "1", "VBUS")
    ff = s.add("power:PWR_FLAG", "#FLG", (75, 160))
    s.connect(ff, "1", "VBUS_F")
    tps = [("VDD5", 380, 200), ("+3V3", 395, 200), ("GND", 380, 250)]
    for net, tx, ty in tps:
        tp = s.add("Connector:TestPoint", "TP", (tx, ty), value=net, footprint=FP_TP)
        s.connect(tp, "1", net)
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
    root.text("Proto40: STM32C071 controller + 2 × (40 fixture nodes + shell + internal test nodes).\n"
              "Generated by hardware/gen/proto40.py. See docs/design-review-and-kicad-plan.md.", 20, 12)
    p = root.sheet("Power", pwr, (30, 40), (40, 10), [("USB_DP", "bidirectional", "R"),
                                                       ("USB_DM", "bidirectional", "R")])
    m = root.sheet("MCU", mcu, (110, 40), (45, 2.54 * 18), MCU_PINS)
    cs = root.sheet("Control", ctrl, (230, 40), (45, 2.54 * 12), CTRL_PINS)
    sa = root.sheet("SideA", side, (330, 40), (45, 2.54 * 10), SIDE_PINS)
    sb = root.sheet("SideB", side, (330, 150), (45, 2.54 * 10), SIDE_PINS)
    root.nets(p, {"USB_DP": "USB_DP", "USB_DM": "USB_DM"})
    for n, _, _ in MCU_PINS:
        root.connect(m, n, n)
    for n, _, side_ in CTRL_PINS:
        if side_ == "L":
            root.connect(cs, n, n)
    root.nets(cs, {"SCK5": "SCK5", "MOSI5": "CTRL_A_IN", "RCLK5": "RCLK5", "PL5_N": "PL5_N", "OE5_N": "OE5_N",
                   "BIAS_EN5_N": "BIAS_EN5_N", "STIM": "STIM", "SENSE_LAST": "SENSE_LAST"})
    for sh, tag in ((sa, "A"), (sb, "B")):
        root.nets(sh, {"STIM": "STIM", "SCK5": "SCK5", "RCLK5": "RCLK5", "PL5_N": "PL5_N", "OE5_N": "OE5_N",
                       "BIAS_EN_N": "BIAS_EN5_N", "ID_SDA": "ID_SDA", "ID_SCL": "ID_SCL",
                       "ID_WP": f"ID_WP_{tag}", "PRESENT_N": f"PRESENT_{tag}_N", "LOOP": "LOOP",
                       "ID_A0": "GND" if tag == "A" else "+3V3"})
    root.nets(sa, {"CTRL_IN": "CTRL_A_IN", "CTRL_OUT": "CTRL_AB", "SENSE_IN": "GND", "SENSE_OUT": "SENSE_AB"})
    root.nets(sb, {"CTRL_IN": "CTRL_AB", "CTRL_OUT": None, "SENSE_IN": "SENSE_AB", "SENSE_OUT": "SENSE_LAST"})
    bases = {(): 0, ("Power",): 100, ("MCU",): 200, ("Control",): 300, ("SideA",): 1000, ("SideB",): 2000}

    def base_of(names):
        if names in bases:
            return bases[names]
        side_base = bases[names[:1]]
        return side_base + 100 * int(names[1][1:])

    Project(PRJ, root, base_of).write(OUT)


if __name__ == "__main__":
    build()
