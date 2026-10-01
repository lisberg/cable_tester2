# Adapter EEPROM – Identity & Embedded Test Profile

Status: **Draft v0.1** · Related: `design-review-and-kicad-plan.md` (F11, §1.5, D10)

## 1. Purpose

Each fixture adapter carries an I²C EEPROM. Originally it only identified the adapter. This spec
extends it so an adapter can also carry **the complete test definition** for the cable(s) it is made
for. Plugging in a matching adapter pair is then enough to run a production test **without a PC**:
operator presses *Start*, the tester reads the profile from the adapter, runs it and shows PASS/FAIL.

Design rules:

1. **Store the intent, not the scan.** The EEPROM stores the expected *netlist* plus a short list of
   test *steps*. The controller derives every expected bitmap at run time. Storing raw bitmaps would
   cost 400 sources × 50 B = 20 kB per polarity; the netlist of a 200‑wire cable is ~1 kB.
2. **Adapter‑local pin space.** The profile refers to *connector pins on the adapters* (e.g.
   "this adapter pin 12" ↔ "partner adapter pin 7"). Each adapter also stores its own
   pin → tester‑channel map. The adapter wiring and the cable definition stay separate, so the same
   cable profile works whichever bank side an adapter is plugged into.
3. **Everything is versioned and CRC‑protected.** The controller refuses to run a corrupted or
   unsupported profile, and says why.
4. **The PC remains authoritative when connected.** A host‑supplied profile overrides the EEPROM.
   The host tool is also the only thing that writes profiles.

## 2. Hardware requirements (adapter + base)

| Item | Requirement |
|---|---|
| EEPROM | I²C, **32 kB minimum (24xx256 class)**. Use a footprint (SOIC‑8/TSSOP‑8) that also takes 64 kB (24xx512 class) parts. A part with a factory‑programmed unique serial number is preferred. Otherwise, add a separate small UID EEPROM at a different address. |
| Address | A0–A2 strapped **through the base connector** (side A = `000`, side B = `001`). The adapter PCB leaves A0–A2 to the connector, so identical adapter designs work on either side. |
| Write protect | `WP` pin routed to the base connector. The controller drives it (default **protected**: pulled high on the adapter, controller only pulls low in *program mode*). A solder jumper on the adapter can force permanent protection for released fixtures. |
| Presence | Dedicated presence‑detect pin (short/late‑mating contact if connector allows). The EEPROM is only accessed after presence is stable for ≥ 100 ms. |
| Bus | 100 kHz default, 400 kHz allowed. Series 33–100 Ω + ESD on SDA/SCL at the base connector. Pull‑ups on the controller only, not on the adapter. |
| Multi‑bank adapters | An adapter spanning several bank connectors has **one** EEPROM, wired to its *primary* (lowest‑numbered) bank connector. The header records which bank connectors the adapter occupies, and firmware checks it. |

Read time: a full 32 kB at 400 kHz is ≈ 0.8 s. Firmware caches the last profile in RAM, keyed by
`(UID, profile CRC32)`, and only re‑reads the header (64 B) on re‑insertion.

## 3. Memory map

All multi‑byte fields are **little‑endian**. Offsets are absolute byte addresses.

```
0x0000  ┌──────────────────────────────┐
        │ Header (64 B, fixed)         │  write‑protected region
0x0040  ├──────────────────────────────┤
        │ Section directory (≤ 16 × 8B)│
0x00C0  ├──────────────────────────────┤
        │ Sections (TLV, page aligned) │  PINMAP, LABELS, PROFILE(s), …
        │                              │
END-1k  ├──────────────────────────────┤
        │ Wear / usage log (1 kB)      │  writable in normal mode*
END     └──────────────────────────────┘
```

\* If the part supports only whole‑chip WP, the usage log moves to the controller's flash, keyed by
adapter UID.

### 3.1 Header (0x0000, 64 bytes)

| Off | Size | Field | Notes |
|---|---|---|---|
| 0x00 | 4 | `magic` | ASCII `CTFX` |
| 0x04 | 1 | `fmt_major` | Incompatible changes. Firmware rejects unknown major. |
| 0x05 | 1 | `fmt_minor` | Additive changes. Firmware ignores unknown sections/opcodes it can skip. |
| 0x06 | 2 | `hdr_len` | = 64 |
| 0x08 | 2 | `adapter_type` | Family/design ID (assigned in a registry in `hardware/adapters/README.md`) |
| 0x0A | 1 | `adapter_rev` | PCB revision |
| 0x0B | 1 | `flags` | b0 = has profile, b1 = primary adapter of pair, b2 = single‑ended fixture (both cable ends on this adapter) |
| 0x0C | 1 | `bank_mask` | Bank connectors occupied (b0 = bank 0 …) |
| 0x0D | 1 | reserved | 0xFF |
| 0x0E | 2 | `pin_count` | Number of adapter connector pins mapped |
| 0x10 | 16 | `serial` | Adapter serial (ASCII, NUL padded); UID chip value is read separately |
| 0x20 | 2 | `dir_offset` | = 0x0040 |
| 0x22 | 1 | `dir_count` | Number of directory entries |
| 0x23 | 1 | reserved | 0xFF |
| 0x24 | 4 | `prog_timestamp` | Unix time of last programming |
| 0x28 | 2 | `prog_tool_ver` | Host tool version that wrote the image |
| 0x2A | 18 | reserved | 0xFF |
| 0x3C | 4 | `hdr_crc32` | CRC‑32/ISO‑HDLC over 0x00–0x3B |

### 3.2 Section directory (8 bytes per entry)

| Off | Size | Field |
|---|---|---|
| 0 | 1 | `type` (see below) |
| 1 | 1 | `instance` (e.g. profile number 0..n) |
| 2 | 2 | `offset` (absolute) |
| 4 | 2 | `length` (bytes, excl. CRC) |
| 6 | 2 | reserved |

Each section ends with a 4‑byte CRC‑32 over its body.

| Type | Name | Required |
|---|---|---|
| 0x01 | `PINMAP` | yes |
| 0x02 | `LABELS` | optional (reports fall back to "pin n") |
| 0x10 | `PROFILE` | optional, 0..n instances |
| 0x20 | `STRINGS` | optional (operator prompts, profile names) |
| 0x7F | `SIGNATURE` | optional (see §6) |
| 0x80–0xFE | vendor/experimental | skipped by firmware |

### 3.3 `PINMAP` – adapter pin → tester channel

```
u16  count
repeat count:
    u16 adapter_pin      // 1-based pin index on the adapter's customer connector(s)
    u16 tester_channel   // channel relative to this adapter's primary bank connector:
                         //   bits 0..7  = channel 0..55 within a bank side
                         //   bits 8..10 = bank offset from primary bank (0..3)
                         //   bit  15    = 1 → shell/chassis contact
```

At run time: `tester_node = f(physical side, primary bank, entry)`, so the same adapter design works on
side A or B.

This section is **generated from the adapter KiCad netlist** by the host tool. It is never hand‑written.

### 3.4 `LABELS`

`u16 count`, then per entry `u16 adapter_pin, u8 len, char[len]` (e.g. `"J1-12"`, `"P3 A7"`). This
makes reports read like the cable drawing.

### 3.5 `PROFILE`

A profile = a **cable definition** (expected connectivity) + **test parameters** + **sequence**.

```
PROFILE header (32 B)
    u16  profile_id
    u8   profile_ver
    u8   flags            // b0 = default profile, b1 = requires partner adapter
    u16  partner_type     // required adapter_type on the other side (0 = none / single-ended)
    u8   partner_rev_min
    u8   reserved
    u16  name_str         // index into STRINGS
    u16  net_count
    u16  nets_offset      // relative to section start
    u16  params_offset
    u16  seq_offset
    u16  seq_len
    u32  netlist_hash     // CRC-32 of canonical netlist, for traceability to the cable drawing
    u8   reserved[8]

NETS  (repeat net_count)
    u8   kind             // 0 = conductor, 1 = shell/drain, 2 = diode (see opcode), 3 = resistor
    u8   n                // number of members
    u16  member[n]        // bit 15: 0 = this adapter, 1 = partner adapter
                          // bits 0..14: adapter_pin
    [kind==3: u32 r_nominal_mohm, u16 tol_permille]

Pins not in any net are expected to be **isolated** (connected to nothing).
Pins listed in an IGNORE step are "don't care".

PARAMS
    u16  settle_us        // default per-step settle (0 = firmware default)
    u8   repeats          // full-scan repeats for stability (default 2)
    u8   polarity_mask    // b0 = drive-high pass, b1 = drive-low pass
    u16  max_v_precheck_mv// refuse if any node exceeds this with drive off
    u16  leak_limit       // load-signature threshold (ADC counts or µS, see firmware spec)
    u8   reserved[8]
```

Size estimate for a 200‑wire point‑to‑point cable: 200 nets × (2 + 2 × 2) B = **1.2 kB**. LABELS for
400 pins ≈ 2.4 kB. Sequence < 256 B. **≈ 4 kB per profile**, so a 32 kB part holds several profiles
(e.g. cable variants sharing one fixture) with ample margin.

### 3.6 Sequence opcodes

The sequence is a flat list of steps. Each step is `u8 opcode, u8 len, u8 args[len]`, so firmware
can skip unknown opcodes (forward compatible). Steps run in order. Any FAIL ends the sequence unless
the step sets `continue_on_fail`.

| Op | Mnemonic | Args | Meaning |
|---|---|---|---|
| 0x01 | `PRECHECK` | — | Voltage scan of all nodes with drive off. Refuse if > `max_v_precheck_mv`. **Firmware always runs this first, even if absent.** |
| 0x02 | `SELFTEST` | — | Bias‑rail toggle + internal loopback/known‑open nodes (F2, F5) |
| 0x03 | `EMPTY_CHECK` | — | Optional: confirm fixture has no unexpected connections before DUT insertion |
| 0x10 | `CONTINUITY` | `u8 polarity_mask` | Full matrix scan; compare against NETS (opens, shorts, swaps) |
| 0x11 | `ISOLATION` | `u16 pin_list…` | Check only the listed pins for isolation (faster partial test) |
| 0x12 | `IGNORE` | `u16 pin_list…` | Mark pins as don't‑care for subsequent steps |
| 0x13 | `NET_ONLY` | `u16 net_index…` | Restrict following checks to listed nets (staged tests) |
| 0x20 | `LOAD_SIG` | `u16 net_index, u16 lo, u16 hi` | Analog load‑signature limit for one net (resistive leak/short) |
| 0x21 | `RESISTOR` | `u16 net_index` | Verify a `kind==3` net within tolerance (only coarse, ≥ ~1 kΩ … ~100 kΩ) |
| 0x22 | `DIODE` | `u16 anode_pin, u16 cathode_pin` | Conducts in one polarity only. Feasibility depends on F3 margins; verify on Proto16. |
| 0x30 | `PROMPT` | `u16 str_index, u8 wait` | Show operator message; wait = 0 none, 1 button, 2 presence change |
| 0x31 | `WIGGLE` | `u16 seconds` | Continuous scan while operator flexes the cable; latch any change = intermittent |
| 0x32 | `DELAY` | `u16 ms` | |
| 0x40 | `SET` | `u8 param_id, u16 value` | Override a PARAMS value for following steps |
| 0xF0 | `RESULT` | `u8 policy` | End; policy = report all faults vs. first fault |

Typical default sequence (what the host tool emits if the user specifies nothing):

```
PRECHECK
SELFTEST
CONTINUITY  polarity=both
END
```

## 4. Controller behaviour

```
on adapter insert (presence stable):
    read header A, header B (if present); validate magic, fmt_major, CRC
    if host connected and host profile active  → use host profile (EEPROM = identity only)
    else if primary adapter flags.has_profile:
        pick default PROFILE (or operator-selected instance)
        check partner_type/rev against other adapter → mismatch = refuse, show reason
        load PINMAP of both adapters, build node→net table (400 × u16 = 800 B RAM)
        state = READY (standalone)
    else → state = NO_PROFILE (needs PC)
on Start:
    run sequence; results → USB (if connected), LEDs/display, usage log
```

* **RAM budget (STM32C071, ~24 kB SRAM):** node→net table 0.8 kB, measured frame 50 B, connectivity
  diff working set ~1 kB, profile cache ≤ 8 kB. Profiles larger than the cache are streamed from the
  EEPROM step by step.
* **Primary/partner rule:** the profile lives on the adapter with `flags.b1 = primary`. The partner
  adapter only needs header + PINMAP (+ LABELS). If both carry a profile for each other, the primary
  wins. A single‑ended fixture (`flags.b2`) has no partner.
* **Usage log:** insertion counter and run counter in the wear region, written as a 16‑entry ring of
  `u32 count, u32 crc`. The highest valid entry wins, so a write torn by removal is harmless. Use it to
  schedule connector replacement against the mating‑cycle rating.
* Result logs are **not** written to the adapter EEPROM. They go to the host, or to the controller.

## 5. Host tool (`host/` – later)

* `ctfx build`: adapter KiCad netlist (via `kicad-cli sch export netlist`) + cable definition (CSV /
  wire list / KiCad netlist of the cable drawing) → binary image + human‑readable dump.
* `ctfx verify`: image ↔ sources consistency (run in CI for every adapter project).
* `ctfx program` / `ctfx read`: through the tester over USB. The tester enters program mode, drives
  `WP` low, writes page by page (respecting the page size and t_WR), reads back, compares CRCs and
  re‑asserts `WP`.

## 6. Integrity & optional authenticity

* CRC‑32 per header/section protects against corruption and torn writes.
* Optional `SIGNATURE` section: HMAC‑SHA256 over all sections, with a site key held in the controller.
  This stops an unofficial or edited profile from passing as released in a regulated production
  environment. Not needed for Rev A; the format reserves room for it.

## 7. Open points

* Confirm a 32 kB / 64 kB part with factory unique serial and partial‑array write protect, or accept
  whole‑chip WP and keep the usage log in controller flash.
* Profile selection UI when an adapter carries several profiles (button cycling vs. small display).
* Exact units for `LOAD_SIG` / `leak_limit` depend on the Proto16 analog characterisation.
