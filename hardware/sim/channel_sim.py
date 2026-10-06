#!/usr/bin/env python3
"""Channel-cell analog budget simulation (ngspice, batch mode).

Models one driven net of N member nodes through the full path:
  STIM driver (AHCT, Rdrv) -> Rlim -> mux stage 2 (Ron) -> mux stage 1 (Ron) -> Rs(source)
  -> cable net (C per member) -> Rs(member) -> member input node with Rbias to BIAS_RAIL,
  worst-case leakage, '165 input.
Also: isolated-node leakage offset, settle time vs net size, and +-24 V DC fault currents.

Usage: python3 channel_sim.py [--rs 4700] [--rbias 680e3] > report.md   (needs ngspice on PATH)
"""
import argparse, os, re, subprocess, sys, tempfile

def run(netlist):
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "c.cir")
        open(f, "w").write(netlist)
        out = subprocess.run(["ngspice", "-b", f], capture_output=True, text=True).stdout
    vals = {}
    for m in re.finditer(r"^\s*(\w+)\s*=\s*([-+0-9.eE]+)", out, re.M):
        vals[m.group(1).lower()] = float(m.group(2))
    return vals, out

def driven_net(p, n, vdd, polarity, tran=False):
    """N members on the net besides the source. polarity 'H': drive VDD, bias 0; 'L': mirrored."""
    vdrv, vbias = (vdd, 0.0) if polarity == "H" else (0.0, vdd)
    # leakage worst case: pushes members toward the bias rail (against the drive)
    ileak = p.ileak if polarity == "H" else -p.ileak
    L = [f"* driven net N={n} vdd={vdd} pol={polarity}",
         f"VB bias 0 {vbias}"]
    if tran:
        L.append(f"VD drv 0 PULSE({vbias} {vdrv} 1u 10n 10n 1 2)")
    else:
        L.append(f"VD drv 0 {vdrv}")
    L += [f"Rdrv drv d1 {p.rdrv}", f"Rlim d1 stim {p.rlim}", f"Cstim stim 0 {p.cstim}",
          f"Rmux2 stim mx {p.ron}", f"Rmux1 mx src {p.ron}", f"Csrc src 0 {p.cnode}",
          f"Rbs src bias {p.rbias_min}",
          f"Rss src net {p.rs_max}", f"Cnet net 0 {p.ccable}"]
    for i in range(n):
        L += [f"Rw{i} net w{i} {p.rwire}", f"Cw{i} w{i} 0 {p.ccable}",
              f"Rs{i} w{i} m{i} {p.rs_max}", f"Cm{i} m{i} 0 {p.cnode}",
              f"Rb{i} m{i} bias {p.rbias_min}", f"Il{i} m{i} 0 {ileak}"]
    worst = f"m{n-1}"
    if tran:
        L += [".tran 0.5u 2m", ".control", "run",
              f"meas tran tset WHEN v({worst})={'%g' % (p.vih_frac*vdd if polarity=='H' else (1-p.vih_frac)*vdd)} {'RISE' if polarity=='H' else 'FALL'}=1",
              "print tset", ".endc", ".end"]
    else:
        L += [".op", ".control", "run", f"let vm = v({worst})", "print vm", ".endc", ".end"]
    return "\n".join(L)

def isolated_node(p, vdd):
    return "\n".join(["* isolated node, leakage worst case toward VDD",
        "VB bias 0 0", f"Rb m bias {p.rbias_max}", f"Il 0 m {p.ileak}", f"Rs m ext {p.rs_max}",
        f"Cm m 0 {p.cnode}", ".op", ".control", "run", "let vm=v(m)", "print vm", ".endc", ".end"])

def fault(p, vext, vdd):
    """DC fault on EXT: TVS (standoff >= 28 V, off), Rs, external low-leakage clamps (BAV199 class,
    high Vf) in parallel with the IC-internal ESD diodes of the mux and '165 inputs."""
    return "\n".join([f"* fault {vext} V",
        ".model DEXT D(IS=5e-12 N=1.8 RS=2)",      # BAV199-class: pA leakage, ~0.9 V @ 5 mA
        ".model DINT D(IS=1e-14 N=1.0 RS=30)",     # CMOS input ESD diode (two ICs lumped)
        f"VE ext 0 {vext}", f"Rs ext m {p.rs_min}",
        "D1 m vdd DEXT", "D2 0 m DEXT",
        "Vsu m mi 0", "D3 mi vdd DINT", "D4 0 mi DINT",
        f"VDD vdd 0 {vdd}",
        ".op", ".control", "run", "let i_rs = (v(ext)-v(m))/" + str(p.rs_min),
        "let p_rs = i_rs*i_rs*" + str(p.rs_min), "let vm = v(m)", "let i_ic = i(vsu)",
        "print i_rs p_rs vm i_ic", ".endc", ".end"])

def max_net(p, step=4, limit=128):
    n_ok = 0
    for n in range(step, limit + 1, step):
        if all(run(driven_net(p, n, v, "H"))[0]["vm"] / v >= p.vih_frac for v in (4.4, 5.25)):
            n_ok = n
        else:
            break
    return n_ok

def sensitivity(p):
    import copy
    print("## 5. Sensitivity: Rs / Rbias / leakage\n")
    print("Guaranteed net size (worst case), isolated‑node offset at 4.4 V (limit 0.25·VDD = 1.10 V), and Rs "
          "dissipation at −30 V.\n")
    print("| Rs | Rbias | leakage/node | N guaranteed | V isolated | P(Rs) @ −30 V |")
    print("|---|---|---|---|---|---|")
    for rs, rb, il in [(4700, 470e3, 2e-6), (4700, 470e3, 0.5e-6), (4700, 680e3, 1e-6), (4700, 1e6, 0.5e-6),
                       (3300, 680e3, 1e-6), (3300, 1e6, 0.5e-6), (2200, 1e6, 0.5e-6)]:
        q = copy.copy(p); q.rs, q.rbias, q.ileak = rs, rb, il
        q.rs_max, q.rs_min = rs * (1 + p.tol), rs * (1 - p.tol)
        q.rbias_min, q.rbias_max = rb * (1 - p.tol), rb * (1 + p.tol)
        n = max_net(q)
        iso = run(isolated_node(q, 4.4))[0]["vm"]
        f = run(fault(q, -30, 5.45))[0]
        mark = " ◀ chosen" if (rs, rb, il) == (p.rs, p.rbias, p.ileak) else ""
        print(f"| {rs/1e3:g} kΩ | {rb/1e3:g} kΩ | {il*1e6:g} µA | {n} | {iso:.2f} V{' ✗' if iso > 1.10 else ''} | "
              f"{f['p_rs']*1e3:.0f} mW{' ✗' if f['p_rs'] > 0.2 else ''}{mark} |")
    print()

def main():
    a = argparse.ArgumentParser()
    a.add_argument("--rs", type=float, default=4700)
    a.add_argument("--rbias", type=float, default=680e3)
    a.add_argument("--tol", type=float, default=0.01)
    a.add_argument("--ileak", type=float, default=1e-6, help="worst-case leakage per node at 40 °C ambient [A]")
    a.add_argument("--ron", type=float, default=20, help="mux Ron per stage, worst case [ohm]")
    a.add_argument("--rdrv", type=float, default=50)
    a.add_argument("--rlim", type=float, default=150)
    a.add_argument("--ccable", type=float, default=500e-12, help="cable C per member (5 m)")
    a.add_argument("--cnode", type=float, default=50e-12, help="mux + 165 + clamp + TVS per node")
    a.add_argument("--cstim", type=float, default=100e-12)
    a.add_argument("--rwire", type=float, default=0.5)
    a.add_argument("--vih", type=float, default=0.70, help="VIH(max) as fraction of VDD")
    a.add_argument("--margin", type=float, default=0.05, help="extra margin as fraction of VDD")
    p = a.parse_args()
    p.rs_max, p.rs_min = p.rs * (1 + p.tol), p.rs * (1 - p.tol)
    p.rbias_min, p.rbias_max = p.rbias * (1 - p.tol), p.rbias * (1 + p.tol)
    p.vih_frac = p.vih + p.margin

    print(f"# Channel cell simulation – Rs = {p.rs:g} Ω, Rbias = {p.rbias:g} Ω\n")
    print("Generated by `hardware/sim/channel_sim.py` (ngspice). Worst‑case corners: Rs +1 %, Rbias −1 %, "
          f"leakage {p.ileak*1e6:g} µA/node against the drive, mux Ron {p.ron:g} Ω/stage, "
          f"driver {p.rdrv:g} Ω + Rlim {p.rlim:g} Ω, cable {p.ccable*1e12:g} pF + node {p.cnode*1e12:g} pF per member.\n")

    print("## 1. Static level on the weakest net member vs. net size\n")
    print(f"Pass criterion: ≥ {p.vih_frac:.2f}·VDD (VIH(max) 0.70·VDD + {p.margin:.2f}·VDD margin). "
          "Typical 74HC switching point ≈ 0.5·VDD. Low polarity mirrors high polarity, so only high is shown.\n")
    print("| N members | VDD 4.40 V: V (ratio) | VDD 5.25 V: V (ratio) | worst case | typical (0.5·VDD) |")
    print("|---|---|---|---|---|")
    nmax_wc = nmax_typ = 0
    for n in [1, 2, 4, 8, 16, 24, 32, 40, 48, 64, 96, 128]:
        cells, ok_all, typ_all = [], True, True
        for vdd in (4.4, 5.25):
            v, _ = run(driven_net(p, n, vdd, "H"))
            r = v["vm"] / vdd
            cells.append(f"{v['vm']:.2f} V ({r:.2f})")
            ok_all &= r >= p.vih_frac; typ_all &= r >= 0.5 + p.margin
        if ok_all: nmax_wc = n
        if typ_all: nmax_typ = n
        print(f"| {n} | {cells[0]} | {cells[1]} | {'PASS' if ok_all else 'fail'} | {'PASS' if typ_all else 'fail'} |")
    print(f"\n**Guaranteed net size (worst case): ≥ {nmax_wc} members. Typical: ≥ {nmax_typ} members.**\n")

    print("## 2. Isolated node offset (leakage)\n")
    for vdd in (4.4, 5.25):
        v, _ = run(isolated_node(p, vdd))
        print(f"* VDD {vdd} V: isolated node sits at {v['vm']:.3f} V; VIL(min) = 0.30·VDD = {0.3*vdd:.2f} V → "
              f"{'PASS' if v['vm'] <= (0.3-p.margin)*vdd else 'FAIL'} (margin {0.3*vdd - v['vm']:.2f} V)")
    print()

    print("## 3. Settle time after the stimulus switches (5 m cable)\n")
    print(f"Time from drive edge until the weakest member crosses {p.vih_frac:.2f}·VDD (VDD 4.4 V). Firmware settle time "
          "per step must exceed this. Releasing a net uses active discharge, which is the same RC path.\n")
    print("| N members | settle |")
    print("|---|---|")
    for n in [1, 2, 4, 8, 16, 32, 36]:
        v, out = run(driven_net(p, n, 4.4, "H", tran=True))
        t = v.get("tset")
        print(f"| {n} | {t*1e6 - 1:.1f} µs |" if t else f"| {n} | does not reach threshold |")
    print()

    print("## 4. DC fault on a fixture node (powered, VDD5 held by the shunt clamp at 5.45 V)\n")
    print("| EXT | I(Rs) | P(Rs) | node voltage | share into IC ESD diodes |")
    print("|---|---|---|---|---|")
    for vext in (24, 30, -24, -30):
        v, _ = run(fault(p, vext, 5.45))
        print(f"| {vext:+d} V | {v['i_rs']*1e3:.2f} mA | {v['p_rs']*1e3:.0f} mW | {v['vm']:.2f} V | {abs(v['i_ic'])*1e3:.2f} mA |")
    print("\nRs (1206, ≥ 0.25 W) covers the dissipation. A high‑Vf low‑leakage external clamp does **not** take the "
          "current away from the IC input diodes: most of it flows through the ICs. The bound is therefore Rs itself. "
          "Keep the per‑input injection below the IC absolute‑maximum clamp current (74HC: ±20 mA; TMUX1308: check "
          "datasheet), and make the VDD5 shunt clamp absorb the sum.\n")
    sensitivity(p)

if __name__ == "__main__":
    main()
