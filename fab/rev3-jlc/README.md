# LibreBoard rev3: JLCPCB order files

Generated with `python3 fab/make_jlc.py` (KiCad 10.0.6 `kicad-cli`) from branch `rev3`. Re-run the
script after any board change; it rewrites everything in this folder.

| File | What it is |
|---|---|
| `libreboard-rev3-gerbers.zip` | Upload this for the PCB: 13 Gerber layers + plated/non-plated Excellon drill files (also unzipped in `gerbers/`). The zip is git-ignored; the script recreates it. |
| `libreboard-rev3-bom-jlc.csv` | Assembly BOM: 88 lines, 187 parts, all with LCSC numbers. |
| `libreboard-rev3-cpl-jlc.csv` | Placement file: the same 187 parts, all on the top side. |
| `libreboard-rev3-bom-jlc-smt-only.csv`, `libreboard-rev3-cpl-jlc-smt-only.csv` | The same without the 16 through-hole parts (171 parts, 80 lines), for fitting those by hand; see below. |
| `libreboard-rev3-tht-hand-fit.csv` | Those 16 parts with their order fields and solder joints. |

## PCB options

- **6 layers**, 125 × 125 mm, 1.6 mm.
- **Stackup:** the KiCad stackup is 0.0994 mm prepreg (L1–L2, L5–L6), 0.55 mm cores and 0.1088 mm prepreg
  (L3–L4). Pick the JLC 6-layer 1.6 mm stackup with those values (JLC06161H-3313, as far as we can tell;
  check the numbers in JLC's picker). The 90 Ω and 100 Ω pair widths in the net classes assume it.
- **Impedance control:** yes (USB 3 / PCIe / USB 2 pairs 90 Ω, Ethernet / CSI-DSI pairs 100 Ω).
- **Via covering: epoxy-filled and capped.** Vias sit inside SMD pads (J15's 0.3 mm USB-C pads, U15, U16,
  C57–C59 and the exposed pads of U11 and U21); open vias there would wick the solder away.
- **Surface finish: ENIG** for this run (OSP is about half the price; see below). Lead-free HASL is not an
  option: it is too uneven for the 0.4 mm-pitch CM5 connectors, the QFNs and USB-C.

### ENIG or OSP

Both finishes are flat, so both work for the fine-pitch parts JLC places straight after making the board.
They differ in what happens afterwards:

| | ENIG (nickel + thin gold) | OSP (organic coating on bare copper) |
|---|---|---|
| Hand soldering after JLC assembly | Pads stay solderable after the reflow oven and weeks of storage. | The coating degrades with heat and time. Empty pads (U17, and U4/U14 if they are hand-fitted) have been through the oven and then sit until you solder them: fine for an SSOP like U17 with plenty of flux, risky for the 3 × 5 mm power QFNs U4/U14, whose large pads need full wetting. |
| Rework during bring-up | Survives repeated heating. | Gets worse with every heat cycle. |
| Test points and storage | Test points stay probe-able; bare boards keep a year or more. | Exposed copper oxidizes; bare boards keep about 6 months. |
| Price | Higher. | About half. |

**Rule of thumb:** OSP is fine when JLC places everything that matters (including U4/U14) and little rework
is expected. Use ENIG when parts are fitted by hand afterwards or when the board will be reworked, which is
the case for this first rev3 run.
- Smallest features: 0.127 mm tracks, 0.1 mm clearance, 0.45 mm vias with 0.2 mm holes.

## Assembly

- **Top side only, SMT + through-hole.** Through-hole parts: J1, J2, J3, J6, J8, J10, J17, J22, J51–J54,
  J100, J101, SW1, SW2, U3.
- **Not placed by JLC:**
  - U1, U2 (Ethernet TVS), C26, J19: not fitted (DNP);
  - U17 TCA9538DBR: buy from DigiKey and fit by hand (excluded from the placement file);
  - M2–M5 SMT nuts: fitted by hand (no footprint);
  - fiducials, test points and mounting holes: copper only.
- **U4, U14 TPS552892QWRYQRQ1:** the BOM line uses LCSC C22375748, which JLC has 0 of. Plan A is JLC's
  global parts sourcing (Mouser has stock); match the BOM line to those parts. If that fails (plan B: fit
  them by hand), exclude U4/U14 from the placement file in KiCad and re-run the script.
- **No JLC footprint:** C63, R7, R19, R20 and R59 (plain 0402 parts). JLC's preview shows them as missing;
  check they are in the order review.

## SMT-only order: through-hole parts by hand

Upload `libreboard-rev3-bom-jlc-smt-only.csv` and `libreboard-rev3-cpl-jlc-smt-only.csv` instead of the
full files to get JLC's price without the through-hole parts. A part counts as through-hole when every
numbered pad is plated through. J11, J15 (USB-C), J22 (HDMI) and J4 (M.2) have through-hole shell stakes
or pegs, but their pins are fine-pitch SMD, so they stay with JLC.

By hand: J1, J6, J10, J17 (USB-C), J2, J3, J8 (pin headers), J51–J54 (fan headers), J100, J101 (screw
terminals), SW1, SW2 and U3 (MagJack): 181 solder joints per board. Two of them are only sold by LCSC,
so buy these instead:
- **U3:** Taoglas **TMJG4926HENL** (Mouser 960-TMJG4926HENL), the original part; same pinout and
  footprint as the LINK-PP LPJG0926HENL. **Not TMJG0813GENL** (see `bom/rev3-sourcing.md`).
- **J2:** Molex **0010897140** C-Grid header (DigiKey WM9875-ND).

**Parts for 10 boards at list prices (2026-10-12):** about **$145** at JLC (JLC prices of the 16 parts) and
about **$191** at DigiKey/Mouser:

| Parts (10 boards) | DigiKey/Mouser | Price |
|---|---|---|
| J1, J6, J10, J17 × 40 | Molex 216989-0001, Mouser 538-216989-0001 | $1.24 → $49.60 |
| U3 × 10 | Taoglas TMJG4926HENL, Mouser 960-TMJG4926HENL | $6.75 → $67.50 |
| J2 × 10 | Molex 0010897140, DigiKey WM9875-ND | $1.93 → $19.27 |
| J3 × 10 | Molex 0022032031, DigiKey 900-0022032031-ND | $0.22 → $2.19 |
| J8 × 10 | Würth 61304021121, Mouser 710-61304021121 | $1.70 → $17.00 |
| J51–J54 × 40 | Molex 0470531000, DigiKey WM4330-ND | $0.48 → $19.16 |
| J100, J101 × 20 | Keystone 7790, Mouser 534-7790 | $0.45 → $9.00 |
| SW1, SW2 × 20 | C&K PTS645VK39-2 LFS, Mouser 611-PTS645VK392 | $0.36 → $7.26 |

The parts alone cost about $46 more outside JLC, plus shipping. In return the JLC order loses 8 extended
BOM lines (about $3 setup each) and JLC's through-hole soldering charge: compare the two JLC quotes.

## Placement corrections

JLC places every part from its own footprint (JLCEDA/EasyEDA official library, https://easyeda.com,
https://lceda.cn): the placement point is that footprint's origin and rotation 0 is its orientation, and
both often differ from our KiCad footprints. `python3 fab/jlc_fit.py` downloads JLC's footprint for every
LCSC number on the board (cached in `fab/.easyeda-cache/`, git-ignored), fits its pads onto ours and writes
`fab/jlc-corrections.csv`: per LCSC number and footprint, the rotation to add and where JLC's origin lies
in our footprint. `make_jlc.py` applies that file; for parts without an entry it falls back to a small
table in the script. After changing an LCSC number or a footprint, run `jlc_fit.py`, then `make_jlc.py`.

Checked against the final placement file: every JLC pad lands within 0.2 mm of one of ours (U12: 0.47 mm,
because its hand-soldering pads are longer). Changes from the KiCad position export:

| Parts | Correction | Why |
|---|---|---|
| J1, J6, J10, J17 (through-hole USB-C) | moved 2.5 mm | JLC's origin is the part centre, ours pin 1. |
| J2, J3, J8 pin headers; J51–J54 fan headers | centred; J2/J3/J8 also +270° | Same. |
| J22 HDMI | moved 2.6 mm | Different origin. |
| U3 (Ethernet), J4 (M.2), J7 (microSD), J11, J15 (USB-C), J14, J16 | moved 0.06–2.4 mm | Different origin. |
| Module1, Module2 (CM5 connectors) | +270° | JLC's pin 1 on our pin 1. The +90° used before put it on pin 100. |
| J100, J101 screw terminals | +270° | The four pads are symmetric; JLC's body outline (wire-clamp side) matches ours only this way. |
| SW1, SW2 | +180°, moved 2.6 mm | Only this way do JLC's mounting legs and button land where ours are; before, the button faced into the board. The two switch pins swap, which does not matter for a switch. |
| J5 camera/display FPC | moved 0.2 mm | Placed by pad positions: JLC numbers the contacts from the other end (by number it would be +180°, body and mounting tabs on the wrong side). Our footprint and pinout are Raspberry Pi's own CM5 IO board footprint, so the copper is right; expect JLC's pin-1 mark at our pin-22 end. |
| Q1, Q2, U6, U12, U15, U18, U19 (SOT-23 family) | +180° | JLC's library draws them the other way round. |
| U5, U8, U10, U11, U13, U16, U20, U21, Y1 | +270° (U20 also 0.1 mm) | JLC's library draws them turned. |

Everything else (passives, LEDs, polymer caps, BT1, U4/U14, U7, U9) needs no correction.

**Check in JLC's preview before confirming:**
- Module1, Module2: JLC's pin-1 mark at the bottom end, right-hand row of each connector (Module1 pin 1
  at x 231.4, y 113.1 in KiCad; Module2 pin 101 at x 197.4, y 113.1).
- SW1, SW2: buttons face the board edge, as on the silkscreen.
- J100, J101: the wire clamp on the same side as the silkscreen outline.
- BT1: its pads are symmetric and JLC's outline is too different from ours to decide, so it keeps KiCad's
  orientation; check that the cell opening matches the silkscreen.
