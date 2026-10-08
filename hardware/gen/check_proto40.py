#!/usr/bin/env python3
"""Design-intent audit of the Proto40 netlist (ERC cannot check intent).

Finds parts by sheet path and type and follows pin connectivity, so it does not depend on net names or
reference numbering. Usage: check_proto40.py <proto40.net>   (kicad-cli sch export netlist)
Exits non-zero on any failed assertion.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sexpr import find, first, parse

n = parse(open(sys.argv[1]).read())
comps = {}
for c in find(first(n, "components"), "comp"):
    ref = first(c, "ref")[1]
    comps[ref] = {
        "value": first(c, "value")[1],
        "part": first(first(c, "libsource"), "part")[1],
        "fp": (first(c, "footprint") or [0, ""])[1],
        "path": first(first(c, "sheetpath"), "names")[1],
    }
nets, pin_net = {}, {}
for x in find(first(n, "nets"), "net"):
    name = first(x, "name")[1]
    nets[name] = [(first(y, "ref")[1], first(y, "pin")[1]) for y in find(x, "node")]
    for rp in nets[name]:
        pin_net[rp] = name
fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)


def parts(part, path=""):
    return sorted((r for r, c in comps.items() if c["part"] == part and c["path"].startswith(path)),
                  key=lambda r: (comps[r]["path"], r))


def kinds(net):
    return collections.Counter(comps[r]["part"] for r, _ in nets[net])


def net(ref, pin):
    return pin_net.get((ref, pin), f"<unconnected {ref}.{pin}>")


def through_r(name):
    """Net on the far side of the single resistor on net `name` (series element)."""
    rs = [(r, p) for r, p in nets[name] if comps[r]["part"] == "R"]
    if len(rs) != 1:
        return f"<{len(rs)} resistors on {name}>"
    r, p = rs[0]
    return net(r, "2" if p == "1" else "1")


def one(part, path):
    p = parts(part, path)
    check(len(p) == 1, f"expected one {part} in {path}, got {p}")
    return p[0] if p else None


rs = [r for r, c in comps.items() if c["value"] == "4.7k" and c["fp"].endswith("R_1206_3216Metric")]
check(len(rs) == 96, f"expected 96 Rs, got {len(rs)}")

for side in ("SideA", "SideB"):
    sp = f"/{side}/"
    j = one("DIN41612_02x32_AC", sp)
    # 1. fixture channels: EXT01..40 = connector pin + TVS + Rs, nothing else
    ext = 0
    for pin in [f"a{i}" for i in range(2, 27)] + [f"c{i}" for i in range(2, 17)]:
        k = kinds(net(j, pin))
        check(k == {"DIN41612_02x32_AC": 1, "D_TVS": 1, "R": 1}, f"{side} {j}.{pin}: {dict(k)}")
        ext += 1
    check(ext == 40, f"{side}: {ext} fixture channels")
    for pin in [f"c{i}" for i in range(17, 27)]:
        check(net(j, pin).startswith("unconnected"), f"{side} {j}.{pin} (EXT41-50) must be unpopulated")
    for pin in ("a1", "a27", "a32", "c1", "c27", "c31", "c32"):
        check(net(j, pin) == "GND", f"{side} {j}.{pin} not GND")
    k = kinds(net(j, "a28"))
    check(k == {"DIN41612_02x32_AC": 1, "D_TVS": 1, "R": 1}, f"{side} SHELL: {dict(k)}")
    # fixture ID lines: ESD diode + series R between the connector and the logic (D14)
    for pin in ("a29", "a30", "c28", "c29", "c30"):
        k = kinds(net(j, pin))
        check(k == {"DIN41612_02x32_AC": 1, "D_TVS": 1, "R": 1}, f"{side} {j}.{pin} ID line protection: {dict(k)}")
    k = kinds(net(j, "a31"))
    check(k == {"DIN41612_02x32_AC": 1, "D_TVS": 1, "R": 1, "C": 1}, f"{side} ID_VCC: {dict(k)}")
    check(through_r(net(j, "a31")) == "+3V3", f"{side} ID_VCC not fed from +3V3")
    strap = through_r(net(j, "c30"))
    check(strap == ("GND" if side == "SideA" else "+3V3"), f"{side} ID_A0 strap wrong: {strap}")
    present = through_r(net(j, "c28"))
    check(present in nets and kinds(present).get("R") == 2, f"{side} PRESENT_N has no pull-up")
    for pin in ("a29", "a30", "c29", "c28"):
        far = through_r(net(j, pin))
        check(far in nets and "STM32C071C8Tx" in kinds(far), f"{side} {j}.{pin} does not reach the MCU")
    # 2. bias rail: 48 Rbias + driver + test point
    drv = one("74AHCT1G125", sp)
    k = kinds(net(drv, "4"))
    check(k.get("R") == 48 and k.get("74AHCT1G125") == 1 and k.get("TestPoint") == 1, f"{side} BIAS_RAIL: {dict(k)}")
    # 3. muxes: 6 first stage + 1 second stage; EN shared, pulled up, driven by the 595
    muxes = parts("TMUX1308", sp)
    check(len(muxes) == 7, f"{side}: {len(muxes)} muxes")
    m2 = [m for m in muxes if comps[m]["path"] == sp][0]          # 2nd stage sits on the side sheet itself
    k = kinds(net(m2, "6"))
    check(k.get("TMUX1308") == 7 and k.get("R") == 1 and k.get("74HC595") == 1, f"{side} EN2_N: {dict(k)}")
    for g, m1 in enumerate(m for m in muxes if m != m2):
        check(net(m1, "3") == net(m2, ["13", "14", "15", "12", "1", "5"][g]),
              f"{side} group mux {m1} output not on 2nd-stage input S{g}")
    # 4. register chain inside the side
    srs = parts("74HC165", sp)
    check(len(srs) == 6, f"{side}: {len(srs)} x 165")
    for a, b in zip(srs, srs[1:]):
        check(net(a, "9") == net(b, "10"), f"{side} chain break {a}.Q7 -> {b}.DS")
    s595 = one("74HC595", sp)
    for pin in ("15", "1", "2", "3", "4", "5", "6", "7", "14", "9"):       # QA..QH, SER, QH'
        check("TestPoint" in kinds(net(s595, pin)), f"{side} {s595}.{pin} has no test point")
    check("TestPoint" in kinds(net(srs[0], "10")) and "TestPoint" in kinds(net(srs[-1], "9")),
          f"{side} sense chain in/out without test point")
    for r in srs:
        check(net(r, "2") == net(s595, "11"), f"{r} CP not on SCK5")
        check(net(r, "1") == net(srs[0], "1"), f"{r} PL not shared")

# 5. cross-side wiring
a165, b165 = parts("74HC165", "/SideA/"), parts("74HC165", "/SideB/")
check(net(a165[0], "10") == "GND", "chain start DS not GND")
check(net(a165[-1], "9") == net(b165[0], "10"), "sense chain A -> B broken")
last = net(b165[-1], "9")
check("74LVC1G125" in kinds(last), "sense chain end not at the MISO buffer")
a595, b595 = parts("74HC595", "/SideA/")[0], parts("74HC595", "/SideB/")[0]
check(net(a595, "9") == net(b595, "14"), "595 chain A -> B broken")
check("74AHCT125" in kinds(net(a595, "14")), "595 chain input not from the level shifter")
check(net(a595, "11") == net(b595, "11"), "SCK5 not shared between sides")
stim = net([m for m in parts("TMUX1308", "/SideA/") if comps[m]["path"] == "/SideA/"][0], "3")
k = kinds(stim)
check(k == {"TMUX1308": 2, "R": 2, "TestPoint": 1}, f"STIM: {dict(k)}")
loop = [nm for nm, nodes in nets.items() if kinds(nm) == {"D_TVS": 2, "R": 2}
        and {comps[r]["path"][:7] for r, _ in nodes} == {"/SideA/", "/SideB/"}]
check(len(loop) == 1, f"LOOP between sides: {loop}")
ja, jb = parts("DIN41612_02x32_AC", "/SideA/")[0], parts("DIN41612_02x32_AC", "/SideB/")[0]
check(through_r(net(ja, "a29")) == through_r(net(jb, "a29")), "ID_SDA not shared")
check(through_r(net(ja, "a30")) == through_r(net(jb, "a30")), "ID_SCL not shared")
check(through_r(net(ja, "c29")) != through_r(net(jb, "c29")), "ID_WP must be per side")
# 6. power
for r, c in comps.items():
    if c["part"] in ("TMUX1308", "74HC165", "74HC595"):
        check(net(r, "16") == "VDD5", f"{r} not on VDD5")
mcu = parts("STM32C071C8Tx")[0]
check(net(mcu, "6") == "+3V3", "MCU VDD not 3V3")

print(f"components: {len(comps)}, nets: {len(nets)}")
print("BOM by part:", dict(collections.Counter(c["part"] for r, c in comps.items() if not r.startswith("#"))))
if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("design-intent audit: PASS")
