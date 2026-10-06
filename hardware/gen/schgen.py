"""Small KiCad 10 schematic generator.

Places library symbols and connects pins with labels or power symbols placed exactly on the pin end
points. Supports multi-instance hierarchical sheets (one .kicad_sch file referenced from several sheet
symbols) with per-instance reference designators.

Correctness is checked by running KiCad ERC on the result (see hardware/gen/README.md).
"""
import copy
import math
import os
import uuid as _uuid

from sexpr import Q, dump, find, first, parse

GRID = 1.27
STD_SYM_DIR = os.environ.get("KICAD_SYMBOL_DIR", "/usr/share/kicad/symbols")
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_LIB = {"cable_tester": os.path.join(HERE, "..", "lib", "cable_tester.kicad_sym")}

_NS = _uuid.UUID("6f1c2a3e-1111-4000-8000-000000000000")


def uid(*key):
    """Deterministic UUID, so regenerating gives stable files (clean diffs)."""
    return str(_uuid.uuid5(_NS, "/".join(str(k) for k in key)))


def snap(v):
    return round(round(v / GRID) * GRID, 4)


def font(hide=False, justify=None, size=1.27):
    e = ["effects", ["font", ["size", size, size]]]
    if justify:
        e.append(["justify"] + justify.split())
    if hide:
        e.append(["hide", "yes"])
    return e


# --------------------------------------------------------------------------------------------- library
class Pin:
    def __init__(self, unit, number, name, etype, x, y, angle, hidden, length=2.54):
        self.unit, self.number, self.name, self.etype = unit, number, name, etype
        self.x, self.y, self.angle, self.hidden, self.length = x, y, angle, hidden, length


class LibSymbol:
    def __init__(self, lib_id, node, pins):
        self.lib_id, self.node, self.pins = lib_id, node, pins
        self.props = {p[1]: p[2] for p in find(node, "property")}
        self.is_power = first(node, "power") is not None


class Library:
    def __init__(self):
        self._files = {}
        self._syms = {}

    def _file(self, lib):
        if lib not in self._files:
            path = PROJECT_LIB.get(lib) or os.path.join(STD_SYM_DIR, lib + ".kicad_sym")
            self._files[lib] = {s[1]: s for s in find(parse(open(path).read()), "symbol")}
        return self._files[lib]

    def get(self, lib_id):
        if lib_id in self._syms:
            return self._syms[lib_id]
        lib, name = lib_id.split(":", 1)
        syms = self._file(lib)
        node = copy.deepcopy(syms[name])
        ext = first(node, "extends")
        if ext:
            parent = copy.deepcopy(syms[ext[1]])
            pname = ext[1]
            child_props = {p[1]: p for p in find(node, "property")}
            merged = ["symbol", Q(name)]
            for e in parent[2:]:
                if isinstance(e, list) and e[0] == "property":
                    merged.append(child_props.pop(e[1], e))
                elif isinstance(e, list) and e[0] == "symbol":
                    e[1] = Q(name + e[1][len(pname):])
                    merged.append(e)
                else:
                    merged.append(e)
            for p in child_props.values():
                merged.insert(2, p)
            node = merged
        pins = []
        for sub in find(node, "symbol"):
            unit = int(sub[1].rsplit("_", 2)[-2])
            for p in find(sub, "pin"):
                at = first(p, "at")
                hidden = first(p, "hide") is not None or "hide" in p
                ln = first(p, "length")
                pins.append(Pin(unit, first(p, "number")[1], first(p, "name")[1], p[1],
                                float(at[1]), float(at[2]), float(at[3]) if len(at) > 3 else 0.0, hidden,
                                float(ln[1]) if ln else 2.54))
        out = copy.deepcopy(node)
        out[1] = Q(lib_id)
        sym = LibSymbol(lib_id, out, pins)
        self._syms[lib_id] = sym
        return sym


LIB = Library()


# --------------------------------------------------------------------------------------------- items
class Sym:
    def __init__(self, sheet, lib_id, prefix, idx, at, rot, unit, value, footprint, fields, dnp, text):
        self.sheet, self.lib = sheet, LIB.get(lib_id)
        self.prefix, self.idx, self.unit = prefix, idx, unit
        self.x, self.y, self.rot = snap(at[0]), snap(at[1]), rot
        self.value = value if value is not None else self.lib.props.get("Value", "")
        self.footprint = footprint if footprint is not None else self.lib.props.get("Footprint", "")
        self.fields, self.dnp, self.text = fields or {}, dnp, text
        self.uuid = uid(sheet.name, "sym", prefix, idx, unit)
        self.used = set()

    def pos(self, key):
        x, y, _ = self.pin(key)
        return x, y

    def pin(self, key, mark=True):
        """Return (x, y, outward_angle) of a pin by number or name (first match, current unit)."""
        cands = [p for p in self.lib.pins if p.unit in (0, self.unit)]
        m = [p for p in cands if p.number == key] or [p for p in cands if p.name == key]
        if not m:
            raise KeyError(f"{self.lib.lib_id} has no pin {key!r} (unit {self.unit})")
        p = m[0]
        r = math.radians(self.rot)
        rx = p.x * math.cos(r) - p.y * math.sin(r)
        ry = p.x * math.sin(r) + p.y * math.cos(r)
        out = (p.angle + 180 + self.rot) % 360
        if mark:
            self.used.add(p.number)
        return snap(self.x + rx), snap(self.y - ry), out

    def _xf(self, px, py):
        r = math.radians(self.rot)
        return (self.x + px * math.cos(r) - py * math.sin(r), self.y - (px * math.sin(r) + py * math.cos(r)))

    def bbox(self):
        """Body bounding box (all graphics of this unit, pins excluded) in schematic coordinates."""
        pts, rect = [], False
        for sub in find(self.lib.node, "symbol"):
            unit = int(sub[1].rsplit("_", 2)[-2])
            if unit not in (0, self.unit):
                continue
            for g in sub[2:]:
                if not isinstance(g, list):
                    continue
                if g[0] == "rectangle":
                    rect = True
                    for k in ("start", "end"):
                        e = first(g, k)
                        pts.append((float(e[1]), float(e[2])))
                elif g[0] == "polyline":
                    pts += [(float(xy[1]), float(xy[2])) for xy in find(first(g, "pts"), "xy")]
                elif g[0] == "circle":
                    c, rr = first(g, "center"), float(first(g, "radius")[1])
                    pts += [(float(c[1]) - rr, float(c[2]) - rr), (float(c[1]) + rr, float(c[2]) + rr)]
                elif g[0] == "arc":
                    pts += [(float(first(g, k)[1]), float(first(g, k)[2])) for k in ("start", "mid", "end")]
        if not pts:
            pts = [(p.x, p.y) for p in self.all_pins()] or [(0, 0)]
        xy = [self._xf(px, py) for px, py in pts]
        xs, ys = [a for a, _ in xy], [b for _, b in xy]
        return min(xs), min(ys), max(xs), max(ys), rect

    def _text_spots(self):
        """Reference/value positions that stay clear of the body, the pins and the wires on them."""
        x0, y0, x1, y1, rect = self.bbox()
        if self.dnp:                          # KiCad draws the DNP cross larger than the body
            x0, y0, x1, y1 = x0 - 1.27, y0 - 1.27, x1 + 1.27, y1 + 1.27
        if self.lib.is_power:
            # value text beyond the symbol, in the direction it points
            base = 270 if self.lib.lib_id.endswith("GND") else 90
            d = (base + self.rot) % 360
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            spot = {270: (cx, y1 + 0.635, "top"), 90: (cx, y0 - 0.635, "bottom"),
                    180: (x0 - 0.635, cy, "right"), 0: (x1 + 0.635, cy, "left")}[d]
            return (spot, spot)
        mode = self.text
        if mode == "auto":
            pins = self.all_pins()
            if rect and len(pins) > 3:
                mode = "ic"
            elif len(pins) == 2:              # two-terminal part: decide by the pin axis, not the body shape
                (ax, ay), (bx, by) = (self._xf(p.x, p.y) for p in pins)
                mode = "right" if abs(ax - bx) < abs(ay - by) else "above"
            elif (x1 - x0) <= (y1 - y0) + 0.01:
                mode = "right"
            else:
                mode = "above"
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if mode == "ic":      # outside the top-left / bottom-left corners, extending away from the body
            return ((x0, y0 - 1.27, "right bottom"), (x0, y1 + 1.27, "right top"))
        if mode == "icright":
            return ((x1, y0 - 1.27, "left bottom"), (x1, y1 + 1.27, "left top"))
        if mode == "right":
            return ((x1 + 0.762, cy - 1.27, "left"), (x1 + 0.762, cy + 1.27, "left"))
        if mode == "left":
            return ((x0 - 0.762, cy - 1.27, "right"), (x0 - 0.762, cy + 1.27, "right"))
        if mode == "below":
            return ((cx, y1 + 1.27, "top"), (cx, y1 + 3.81, "top"))
        return ((cx, y0 - 1.27, "bottom"), (cx, y1 + 1.27, "top"))   # above / below

    def pin_segments(self):
        """Drawn pin lines (connection point → body) in schematic coordinates."""
        segs = []
        for p in self.all_pins():
            if p.hidden or p.length <= 0:
                continue
            a = math.radians(p.angle)
            ex, ey = p.x + p.length * math.cos(a), p.y + p.length * math.sin(a)
            (x1, y1), (x2, y2) = self._xf(p.x, p.y), self._xf(ex, ey)
            segs.append((round(x1, 3), round(y1, 3), round(x2, 3), round(y2, 3)))
        return segs

    def all_pins(self):
        return [p for p in self.lib.pins if p.unit in (0, self.unit)]

    def node(self, instances):
        n = ["symbol", ["lib_id", Q(self.lib.lib_id)], ["at", self.x, self.y, self.rot], ["unit", self.unit],
             ["exclude_from_sim", "no"], ["in_bom", "no" if self.lib.is_power else "yes"],
             ["on_board", "no" if self.lib.is_power else "yes"], ["dnp", "yes" if self.dnp else "no"],
             ["uuid", Q(self.uuid)]]
        ref0 = instances[0][1]
        (rx, ry, rj), (vx, vy, vj) = self._text_spots()
        props = [("Reference", ref0, (rx, ry), rj, self.lib.is_power),
                 ("Value", self.value, (vx, vy), vj, False),
                 ("Footprint", self.footprint, (self.x, self.y), None, True),
                 ("Datasheet", self.lib.props.get("Datasheet", ""), (self.x, self.y), None, True),
                 ("Description", self.lib.props.get("Description", ""), (self.x, self.y), None, True)]
        for k, v in self.fields.items():
            props.append((k, v, (self.x, self.y), None, True))
        for k, v, (px, py), just, hide in props:
            # KiCad adds the symbol rotation to the field angle (store -rot for 90/270). For 180 it keeps the
            # text upright but mirrors the justification, so mirror it back.
            ang = (-self.rot) % 360 if self.rot in (90, 270) else 0
            if self.rot == 180 and just:
                swap = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}
                just = " ".join(swap.get(w, w) for w in just.split())
            n.append(["property", Q(k), Q(v), ["at", round(px, 3), round(py, 3), ang],
                      font(hide=hide, justify=just)])
        for p in self.all_pins():
            n.append(["pin", Q(p.number), ["uuid", Q(uid(self.uuid, "pin", p.number))]])
        n.append(["instances", ["project", Q(self.sheet.project),
                                *[["path", Q(path), ["reference", Q(ref)], ["unit", self.unit]]
                                  for path, ref in instances]]])
        return n


class SheetSym:
    def __init__(self, parent, name, child, at, size, pins):
        self.parent, self.name, self.child = parent, name, child
        self.x, self.y = snap(at[0]), snap(at[1])
        self.w, self.h = snap(size[0]), snap(size[1])
        self.uuid = uid(parent.name, "sheet", name)
        self.pins = {}
        left = [p for p in pins if p[2] == "L"]
        right = [p for p in pins if p[2] == "R"]
        for i, (pname, ptype, side) in enumerate(left):          # pname None = empty row
            if pname:
                self.pins[pname] = (self.x, snap(self.y + 2.54 * (i + 1)), 180, ptype)
        for i, (pname, ptype, side) in enumerate(right):
            if pname:
                self.pins[pname] = (snap(self.x + self.w), snap(self.y + 2.54 * (i + 1)), 0, ptype)

    def pin(self, name):
        x, y, a, _ = self.pins[name]
        return x, y, a

    def node(self, pages):
        n = ["sheet", ["at", self.x, self.y], ["size", self.w, self.h], ["exclude_from_sim", "no"],
             ["in_bom", "yes"], ["on_board", "yes"], ["dnp", "no"], ["fields_autoplaced", "yes"],
             ["stroke", ["width", 0.1524], ["type", "solid"]], ["fill", ["color", 0, 0, 0, 0.0]],
             ["uuid", Q(self.uuid)],
             ["property", Q("Sheetname"), Q(self.name), ["at", self.x, snap(self.y - 0.7), 0],
              font(justify="left bottom")],
             ["property", Q("Sheetfile"), Q(self.child.filename), ["at", self.x, snap(self.y + self.h + 0.7), 0],
              font(justify="left top")]]
        for pname, (x, y, a, ptype) in self.pins.items():
            n.append(["pin", Q(pname), ptype, ["at", x, y, a], ["uuid", Q(uid(self.uuid, "pin", pname))],
                      font(justify="left" if a == 180 else "right")])
        n.append(["instances", ["project", Q(self.parent.project),
                                *[["path", Q(path), ["page", Q(str(page))]] for path, page in pages]]])
        return n


# --------------------------------------------------------------------------------------------- sheet
class Sheet:
    POWER = {"GND": "power:GND", "+3V3": "power:+3V3", "VBUS": "power:VBUS", "VDD5": "cable_tester:VDD5"}

    def __init__(self, name, filename, project, title="", paper="A3"):
        self.name, self.filename, self.project, self.title, self.paper = name, filename, project, title, paper
        self.syms, self.sheets, self.items = [], [], []
        self.segs, self.junctions = [], set()
        self.counters = {}
        self.uuid = uid(filename, "root")

    # -- placement
    def add(self, lib_id, prefix, at, rot=0, value=None, footprint=None, unit=1, fields=None, dnp=False,
            same_as=None, text="auto"):
        if same_as is not None:
            idx = same_as.idx
        else:
            idx = self.counters.get(prefix, 0) + 1
            self.counters[prefix] = idx
        s = Sym(self, lib_id, prefix, idx, at, rot, unit, value, footprint, fields, dnp, text)
        self.syms.append(s)
        return s

    def sheet(self, name, child, at, size, pins):
        s = SheetSym(self, name, child, at, size, pins)
        self.sheets.append(s)
        return s

    # -- connectivity
    def label(self, name, x, y, angle, kind="local", shape="bidirectional"):
        just = {0: "left bottom", 90: "left bottom", 180: "right bottom", 270: "right bottom"}[angle]
        if kind == "local":
            node = ["label", Q(name), ["at", x, y, angle], font(justify=just)]
        elif kind == "global":
            node = ["global_label", Q(name), ["shape", shape], ["at", x, y, angle],
                    font(justify="left" if angle in (0, 90) else "right")]
        else:
            node = ["hierarchical_label", Q(name), ["shape", shape], ["at", x, y, angle],
                    font(justify="left" if angle in (0, 90) else "right")]
        node.append(["uuid", Q(uid(self.filename, "lbl", name, x, y))])
        self.items.append(node)

    def power(self, net, x, y, out_angle):
        lib_id = self.POWER[net]
        default = 270 if net == "GND" else 90           # GND hangs down, rails point up
        rot = (out_angle - default) % 360
        s = self.add(lib_id, "#PWR", (x, y), rot=rot)
        return s

    def nc(self, x, y):
        self.items.append(["no_connect", ["at", x, y], ["uuid", Q(uid(self.filename, "nc", x, y))]])

    def wire(self, x1, y1, x2, y2):
        x1, y1, x2, y2 = snap(x1), snap(y1), snap(x2), snap(y2)
        if (x1, y1) == (x2, y2):
            return
        self.segs.append((x1, y1, x2, y2))
        self.items.append(["wire", ["pts", ["xy", x1, y1], ["xy", x2, y2]],
                           ["stroke", ["width", 0], ["type", "default"]],
                           ["uuid", Q(uid(self.filename, "w", x1, y1, x2, y2))]])

    def path(self, *pts):
        """Polyline through points; a point may be a (sym, pin) tuple. Use hv()/vh() for corners."""
        xy = [p if isinstance(p[0], (int, float)) else p[0].pos(p[1]) for p in pts]
        for (a, b), (c, d) in zip(xy, xy[1:]):
            self.wire(a, b, c, d)
        return xy[-1]

    def hv(self, a, b):
        """Orthogonal route: horizontal first, then vertical."""
        return self.path(a, (b[0], a[1]), b)

    def vh(self, a, b):
        return self.path(a, (a[0], b[1]), b)

    def stub(self, obj, pin, length=2.54):
        """Wire out of a pin along its direction; returns the free end."""
        x, y, a = obj.pin(pin)
        dx = {0: length, 180: -length, 90: 0, 270: 0}[a]
        dy = {0: 0, 180: 0, 90: -length, 270: length}[a]
        self.wire(x, y, x + dx, y + dy)
        return snap(x + dx), snap(y + dy)

    def junction(self, x, y):
        self.junctions.add((snap(x), snap(y)))

    def text(self, s, x, y, size=1.27):
        self.items.append(["text", Q(s), ["exclude_from_sim", "no"], ["at", x, y, 0],
                           font(justify="left top", size=size), ["uuid", Q(uid(self.filename, "txt", s[:40], x, y))]])

    def connect(self, obj, pin, net, kind=None, shape="bidirectional", stub=2.54, rotate=False):
        """Attach net to a pin: power symbol for rails, no-connect for None, label otherwise.
        kind: 'local' (default), 'global', 'hier'. A short wire stub keeps labels off the symbol body."""
        x, y, a = obj.pin(pin)
        if net is None:
            self.nc(x, y)
            return
        if net in self.POWER and kind is None:
            if a in (0, 180) and not rotate:
                # horizontal pin: short stub, then a normally oriented symbol (GND down, rails up)
                x, y = self.stub(obj, pin, max(stub, 2.54))
                self.power(net, x, y, 270 if net == "GND" else 90)
                return
            if stub and stub > 2.54:
                x, y = self.stub(obj, pin, stub)
            self.power(net, x, y, a)
            return
        dx = {0: stub, 180: -stub, 90: 0, 270: 0}[a]
        dy = {0: 0, 180: 0, 90: -stub, 270: stub}[a]
        x2, y2 = snap(x + dx), snap(y + dy)
        if stub:
            self.wire(x, y, x2, y2)
        self.label(net, x2, y2, a, kind or "local", shape)

    def nets(self, obj, mapping, **kw):
        for pin, net in mapping.items():
            self.connect(obj, pin, net, **kw)

    def unused_nc(self):
        """Put no-connect flags on every unused, visible, non-power pin."""
        for s in self.syms:
            if s.lib.is_power:
                continue
            for p in s.all_pins():
                if p.number not in s.used and not p.hidden and p.etype != "no_connect":
                    x, y, _ = s.pin(p.number)
                    self.nc(x, y)

    def pin_points(self):
        pts = []
        for s in self.syms:
            for p in s.all_pins():
                x, y, _ = s.pin(p.number, mark=False)
                pts.append((x, y))
        for sh in self.sheets:
            pts += [(x, y) for x, y, _, _ in sh.pins.values()]
        return pts

    def _auto_junctions(self):
        """Junction wherever three or more connection ends meet, or a wire/pin ends on a wire interior."""
        deg = {}
        for x1, y1, x2, y2 in self.segs:
            for pt in ((x1, y1), (x2, y2)):
                deg[pt] = deg.get(pt, 0) + 1
        for pt in self.pin_points():
            deg[pt] = deg.get(pt, 0) + 1
        out = set()
        for (px, py), d in deg.items():
            for x1, y1, x2, y2 in self.segs:
                inside = (x1 == x2 == px and min(y1, y2) < py < max(y1, y2)) or \
                         (y1 == y2 == py and min(x1, x2) < px < max(x1, x2))
                if inside:
                    d += 2
            if d >= 3:
                out.add((px, py))
        return out

    # -- output
    def write(self, path, instances_of, pages_of, lib_extra=()):
        """instances_of(sheet, sym) -> [(path, ref)], pages_of(sheetsym) -> [(path, page)]."""
        libs = {}
        for s in self.syms:
            libs.setdefault(s.lib.lib_id, s.lib.node)
        root = ["kicad_sch", ["version", 20260306], ["generator", Q("cable_tester_gen")],
                ["generator_version", Q("10.0")], ["uuid", Q(self.uuid)], ["paper", Q(self.paper)],
                ["title_block", ["title", Q(self.title or "${BOARD_NAME}")], ["date", Q("${RELEASE_DATE}")],
                 ["rev", Q("${REVISION}")], ["company", Q("${COMPANY}")], ["comment", 1, Q("${PROJECT}")],
                 ["comment", 2, Q("Generated by hardware/gen – edit the generator, not this file")]],
                ["lib_symbols", *[libs[k] for k in sorted(libs)]]]
        root += self.items
        for jx, jy in sorted(self._auto_junctions() | self.junctions):
            root.append(["junction", ["at", jx, jy], ["diameter", 0], ["color", 0, 0, 0, 0],
                         ["uuid", Q(uid(self.filename, "j", jx, jy))]])
        for s in self.syms:
            root.append(s.node(instances_of(self, s)))
        for sh in self.sheets:
            root.append(sh.node(pages_of(sh)))
        root.append(["sheet_instances", ["path", Q("/"), ["page", Q("1")]]])
        root.append(["embedded_fonts", "no"])
        with open(path, "w") as f:
            f.write(dump(root) + "\n")


# --------------------------------------------------------------------------------------------- project
class Project:
    """Walks the sheet tree, assigns per-instance paths, references and page numbers, writes all files."""

    def __init__(self, name, root, base_of):
        self.name, self.root, self.base_of = name, root, base_of

    def write(self, directory):
        """Every sheet instance has a path: '/<root uuid>' for the root, parent path + '/<sheet uuid>'
        for children. Symbols list one instance per path of their sheet file; sheet symbols list one
        page per path of their parent sheet file."""
        inst, page_of, files = {}, {}, {}
        counter = [0]

        def rec(sheet, path, names):
            counter[0] += 1
            page_of[path] = counter[0]
            files[sheet.filename] = sheet
            inst.setdefault(sheet.filename, []).append((path, self.base_of(names)))
            for sh in sheet.sheets:
                rec(sh.child, f"{path}/{sh.uuid}", names + (sh.name,))

        rec(self.root, f"/{self.root.uuid}", ())

        def instances_of(sheet, sym):
            return [(path, f"{sym.prefix}{base + sym.idx}") for path, base in inst[sheet.filename]]

        def pages_of(sheetsym):
            return [(path, page_of[f"{path}/{sheetsym.uuid}"]) for path, _ in inst[sheetsym.parent.filename]]

        for fn, sheet in files.items():
            sheet.write(os.path.join(directory, fn), instances_of, pages_of)
        return files
