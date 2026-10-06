#!/usr/bin/env python3
"""(Re)build hardware/lib/cable_tester.kicad_sym from KiCad standard symbols plus edits.

Run: python3 make_lib.py   (KICAD_SYMBOL_DIR must point at the KiCad 10 symbol libraries)
"""
import copy, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from sexpr import Q, dump, find, first, parse
from schgen import STD_SYM_DIR, HERE

def load(lib, name):
    syms = {s[1]: s for s in find(parse(open(os.path.join(STD_SYM_DIR, lib + ".kicad_sym")).read()), "symbol")}
    return copy.deepcopy(syms[name])

def rename(node, old, new):
    node[1] = Q(new)
    for sub in find(node, "symbol"):
        sub[1] = Q(new + sub[1][len(old):])
    return node

def set_prop(node, key, value, hide=True):
    for p in find(node, "property"):
        if p[1] == key:
            p[2] = Q(value)
            return
    node.insert(3, ["property", Q(key), Q(value), ["at", 0, 0, 0],
                    ["effects", ["font", ["size", 1.27, 1.27]], ["hide", "yes"]]])

# VDD5: 5 V analog/logic rail (power symbol, net name VDD5)
vdd5 = rename(load("power", "+5V"), "+5V", "VDD5")
set_prop(vdd5, "Value", "VDD5")
set_prop(vdd5, "Description", "Power symbol: 5 V analog/logic rail (filtered VBUS, see review F8)")
set_prop(vdd5, "ki_keywords", "global power")

# TMUX1308: 8:1 single-ended mux, 4051-compatible pinout, pin 7 = NC (verify against TI datasheet)
mux = rename(load("74xx", "74HC4051"), "74HC4051", "TMUX1308")
names = {"A0": "S0", "A1": "S1", "A2": "S2", "A3": "S3", "A4": "S4", "A5": "S5", "A6": "S6", "A7": "S7",
         "A": "D", "S0": "SEL0", "S1": "SEL1", "S2": "SEL2", "VCC": "VDD"}
for sub in find(mux, "symbol"):
    for p in find(sub, "pin"):
        nm = first(p, "name")
        num = first(p, "number")[1]
        if num == "7":
            nm[1] = Q("NC"); p[1] = "no_connect"
        elif nm[1] in names:
            nm[1] = Q(names[nm[1]])
set_prop(mux, "Value", "TMUX1308")
set_prop(mux, "Footprint", "Package_SO:TSSOP-16_4.4x5mm_P0.65mm")
set_prop(mux, "Datasheet", "https://www.ti.com/lit/ds/symlink/tmux1308.pdf")
set_prop(mux, "Description", "8:1 analog multiplexer, 1.62-5.5 V, 1.8 V logic, active-low enable. "
         "Pinout assumed 4051-compatible with pin 7 NC - VERIFY against datasheet before layout.")
set_prop(mux, "ki_keywords", "mux analog switch 8:1")
set_prop(mux, "MPN", "TMUX1308PWR")
set_prop(mux, "Manufacturer", "Texas Instruments")

lib = ["kicad_symbol_lib", ["version", 20251024], ["generator", Q("kicad_symbol_editor")],
       ["generator_version", Q("10.0")], vdd5, mux]
open(os.path.join(HERE, "..", "lib", "cable_tester.kicad_sym"), "w").write(dump(lib) + "\n")
print("wrote cable_tester.kicad_sym: VDD5, TMUX1308")
