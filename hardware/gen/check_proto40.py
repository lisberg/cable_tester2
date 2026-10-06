#!/usr/bin/env python3
"""Design-intent audit of the Proto40 netlist (ERC cannot check intent).

Usage: check_proto40.py <proto40.net>   (kicad-cli sch export netlist --format kicadsexpr)
Exits non-zero on any failed assertion.
"""
import collections, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sexpr import parse, find, first

n = parse(open(sys.argv[1]).read())
comps = {first(c, "ref")[1]: c for c in find(first(n, "components"), "comp")}
val = {r: first(c, "value")[1] for r, c in comps.items()}
part = {r: first(first(c, "libsource"), "part")[1] for r, c in comps.items()}
fp = {r: (first(c, "footprint") or [0, ""])[1] for r, c in comps.items()}
nets = {}
pin_net = {}
for x in find(first(n, "nets"), "net"):
    name = first(x, "name")[1]
    nodes = []
    for y in find(x, "node"):
        ref, pin = first(y, "ref")[1], first(y, "pin")[1]
        fn = first(y, "pinfunction")
        nodes.append((ref, pin, fn[1] if fn else ""))
        pin_net[(ref, pin)] = name
    nets[name] = nodes
fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)


def kinds(net):
    return collections.Counter(part[r] for r, _, _ in nets[net])


def net_of(ref, fn):
    for (r, p), nn in pin_net.items():
        if r == ref and any(f == fn for rr, pp, f in nets[nn] if rr == r and pp == p):
            return nn
    return None


# 1. fixture channels
for side in "AB":
    for ch in range(1, 41):
        nm = f"/Side{side}/EXT{ch:02d}"
        check(nm in nets, f"missing {nm}")
        if nm in nets:
            k = kinds(nm)
            check(k == {"DIN41612_02x32_AC": 1, "D_TVS": 1, "R": 1}, f"{nm}: {dict(k)}")
# 2. node cells: every Rs 4.7k has a node with Rb, C, mux, 165
rs = [r for r in comps if val[r] == "4.7k" and fp[r].endswith("R_1206_3216Metric")]
check(len(rs) == 96, f"expected 96 Rs, got {len(rs)}")
for r in rs:
    node = pin_net[(r, "2")]
    k = kinds(node)
    check(k == {"R": 2, "C": 1, "TMUX1308": 1, "74HC165": 1}, f"node {node}: {dict(k)}")
# 3. bias rails
for side in "AB":
    br = f"/Side{side}/BIAS_RAIL"
    k = kinds(br)
    check(k.get("R") == 48 and k.get("74AHCT1G125") == 1 and k.get("TestPoint") == 1, f"{br}: {dict(k)}")
# 4. STIM bus
k = kinds("/STIM")
check(k == {"TMUX1308": 2, "R": 2, "TestPoint": 1}, f"STIM: {dict(k)}")
# 5. 165 chain: GND -> A.G1..G6 -> B.G1..G6 -> LVC1G125 -> MISO
sr = sorted(r for r in comps if part[r] == "74HC165")
check(len(sr) == 12, f"12 x 165 expected, got {len(sr)}")
order = ["U1102", "U1202", "U1302", "U1402", "U1502", "U1602", "U2102", "U2202", "U2302", "U2402", "U2502", "U2602"]
check(pin_net[(order[0], "10")] == "GND", "chain start DS not GND")
for a, b in zip(order, order[1:]):
    check(pin_net[(a, "9")] == pin_net[(b, "10")], f"chain break {a}.Q7 -> {b}.DS")
last = pin_net[(order[-1], "9")]
check(any(part[r] == "74LVC1G125" for r, _, _ in nets[last]), "chain end not at MISO buffer")
# 6. control chain
s595 = sorted(r for r in comps if part[r] == "74HC595")
check(len(s595) == 2, "2 x 595 expected")
check(pin_net[("U1002", "9")] == pin_net[("U2002", "14")], "595 chain A->B broken")
check(any(part[r] == "74AHCT125" for r, _, _ in nets[pin_net[("U1002", "14")]]), "595 A SER not from level shifter")
# 7. clocks reach all registers
sck = pin_net[("U1002", "11")]
check(sum(1 for r, p, _ in nets[sck] if part[r] == "74HC165" and p == "2") == 12, "SCK5 not on all 165 CP")
check(sum(1 for r, p, _ in nets[sck] if part[r] == "74HC595" and p == "11") == 2, "SCK5 not on both 595")
pl = pin_net[("U1102", "1")]
check(sum(1 for r, p, _ in nets[pl] if part[r] == "74HC165" and p == "1") == 12, "PL5_N not on all 165")
# 8. ID straps and presence
ja, jb = "J1001", "J2001"
check(pin_net[(ja, "c30")] == "GND", "side A ID_A0 not GND")
check(pin_net[(jb, "c30")] == "+3V3", "side B ID_A0 not +3V3")
check(pin_net[(ja, "a29")] == pin_net[(jb, "a29")], "ID_SDA not shared")
check(pin_net[(ja, "c29")] != pin_net[(jb, "c29")], "ID_WP must be per side")
for j in (ja, jb):
    for p in ("a1", "a27", "a32", "c1", "c27", "c31", "c32"):
        check(pin_net[(j, p)] == "GND", f"{j}.{p} not GND")
    for p in [f"a{i}" for i in range(17, 27)] + [f"c{i}" for i in range(17, 27)]:
        ch = int(p[1:]) - 1 + (25 if p[0] == "c" else 0)
        if ch > 40:
            check(pin_net[(j, p)].startswith("unconnected"), f"{j}.{p} (EXT{ch}) should be unpopulated")
# 9. loopback between sides
loop = [nm for nm in nets if nm.endswith("LOOP")]
check(len(loop) == 1 and kinds(loop[0]) == {"D_TVS": 2, "R": 2}, f"LOOP: {[(l, dict(kinds(l))) for l in loop]}")
# 10. power
for r in comps:
    if part[r] in ("TMUX1308", "74HC165", "74HC595"):
        vp = {"TMUX1308": "16", "74HC165": "16", "74HC595": "16"}[part[r]]
        check(pin_net[(r, vp)] == "VDD5", f"{r} not on VDD5")
mcu = [r for r in comps if part[r].startswith("STM32C071")][0]
check(pin_net[(mcu, "6")] == "+3V3", "MCU VDD not 3V3")
# 11. 2nd-stage mux enables share EN2_N with first stage, pulled up
for side, m2 in (("A", "U1001"), ("B", "U2001")):
    en = pin_net[(m2, "6")]
    k = kinds(en)
    check(k.get("TMUX1308") == 7 and k.get("R") == 1 and k.get("74HC595") == 1, f"EN2_N {side}: {dict(k)}")

print(f"components: {len(comps)}, nets: {len(nets)}")
print("BOM by part:", dict(collections.Counter(part[r] for r in comps if not r.startswith("#"))))
if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("design-intent audit: PASS")
