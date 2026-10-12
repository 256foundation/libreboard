# LibreBoard rev3: JLCPCB order files

Generated with `python3 fab/make_jlc.py` (KiCad 10.0.6 `kicad-cli`) from branch `rev3`. Re-run the
script after any board change; it rewrites everything in this folder.

| File | What it is |
|---|---|
| `libreboard-rev3-gerbers.zip` | Upload this for the PCB: 13 Gerber layers + plated/non-plated Excellon drill files (also unzipped in `gerbers/`). The zip is git-ignored; the script recreates it. |
| `libreboard-rev3-bom-jlc.csv` | Assembly BOM: 88 lines, 187 parts, all with LCSC numbers. |
| `libreboard-rev3-cpl-jlc.csv` | Placement file: the same 187 parts, all on the top side. |

## PCB options

- **6 layers**, 125 × 125 mm, 1.6 mm.
- **Stackup:** the KiCad stackup is 0.0994 mm prepreg (L1–L2, L5–L6), 0.55 mm cores and 0.1088 mm prepreg
  (L3–L4). Pick the JLC 6-layer 1.6 mm stackup with those values (JLC06161H-3313, as far as we can tell;
  check the numbers in JLC's picker). The 90 Ω and 100 Ω pair widths in the net classes assume it.
- **Impedance control:** yes (USB 3 / PCIe / USB 2 pairs 90 Ω, Ethernet / CSI-DSI pairs 100 Ω).
- **Via covering: epoxy-filled and capped.** Vias sit inside SMD pads (J15's 0.3 mm USB-C pads, U15, U16,
  C57–C59 and the exposed pads of U11 and U21); open vias there would wick the solder away.
- **Surface finish: ENIG** (0.4 mm-pitch CM5 connectors, QFNs, USB-C).
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
- **Rotations:** the placement file uses KiCad's rotations. JLC's part library is not always drawn in the
  same orientation, so check every part below in JLC's placement preview before confirming:
  - polarised: C3, C20, C51, C69 (polymer caps), D1–D3 (LEDs), BT1;
  - ICs and transistors: U4–U16, U18–U21, Q1, Q2, Y1;
  - connectors and switches: J1–J22, J51–J54, J100, J101, Module1, Module2 (the two CM5 connectors), U3, SW1, SW2.
