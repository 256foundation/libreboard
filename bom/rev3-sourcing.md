# LibreBoard rev3 — part sourcing (DigiKey + JLCPCB)

Generated 2026-10-11 from the `rev3` schematic (commit `1abcc2e`), assuming a **10-board build**.
Full per-part data: [`rev3-sourcing.csv`](rev3-sourcing.csv) (one row per part number) and
[`rev3-sourcing.json`](rev3-sourcing.json) (same data plus the rules and manual decisions used).

**Scope:** 223 components, 93 part numbers. 28 parts have no part number on purpose: fiducials,
mounting holes and test points.

**What was done**
- **DigiKey:** checked every existing DigiKey number against its manufacturer part number. Blank, wrong
  or non-DigiKey numbers were filled or fixed. Reel (TR) numbers were kept, as you asked.
- **JLCPCB/LCSC:** found an LCSC code for 88 of the 93 part numbers.
  - Passives use JLC Basic or Preferred equivalents where one exists with the same value, size,
    tolerance, voltage and dielectric (or better).
  - ICs, connectors and other critical parts use the exact part.
- **Written to the schematic** in `875b361` (hidden `LCSC` field plus the DigiKey fixes); connectivity, values
  and footprints unchanged, ERC unchanged at 342.

## 1. Decisions (made 2026-10-11)

| Part | Problem | Decision |
|---|---|---|
| **U4, U14** buck-boost | TPS552892RYQR not available anywhere. | **Switched to TPS552892QWRYQRQ1**, the AEC-Q100 version (the automotive grade itself is not needed; it is the only TPS552892 in stock): same 21 pins, RYQ package, VREF 1.2 V and 3–36 V input in both TI datasheets, so the footprint and feedback dividers stay. **Plan A:** have JLC buy 20 through its global parts sourcing from Mouser (595-PS552892QWRYQRQ1, 25 in stock on 2026-10-11; JLC and DigiKey have 0). **Plan B, if JLC cannot get them:** buy them at Mouser and fit U4/U14 by hand after assembly (they would then be excluded from the placement file like U17). Not used: TPS55289RYQR (JLC 4,086, same footprint) keeps its output off until enabled over I²C, so it cannot start U14, which powers the CM5; TPS552882RPMR (JLC 5,955) needs a new footprint and layout. |
| **U17** TCA9538DBR | JLC has 1. | **Hand-fitted:** buy from DigiKey (296-43160-2-ND) and solder it after assembly. Excluded from the placement file (symbol `in_pos_files no`, footprint `exclude_from_pos_files`); deselect it in JLC's BOM step. |
| **U16** LED buffer | SOT-553 (DRLR) has 0 at JLC. | **Footprint changed to SC-70-5: SN74AHCT1G125DCKR** (C350557, 16.6k at JLC). Same pinout (1 OE, 2 A, 3 GND, 4 Y, 5 VCC). SC-70-5 instead of SOT-23-5 because U16 sits 1.5–2.3 mm from C71, C70, R9 and R52. Needs F8 and re-routing. |
| **U3** MagJack | TMJG4926HENL: JLC 0, DigiKey 4. | **Switched to LINK-PP LPJG0926HENL** (C22457393, 2,305 at JLC); same schematic, pinout and footprint; rated 0–70 °C instead of −40 to +85 °C. DigiKey fallback with the right pinout: TMJG4926HENL. **Never accept TMJG0813GENL**: the Rev1 boards were fitted with it (pin 9 = centre tap, pin 10 = ground), so gigabit could never link. |
| **U1, U2** Ethernet TVS | — | **Not fitted (DNP)**, footprints kept; see section 3. |
| **BT1** coin-cell holder | BAT-HLD-007-SMT-TR: JLC 0. | **Switched to Keystone 3000TR** (C6997853, 715 at JLC; DigiKey 36-3000TR-ND). It is the original 12 mm retainer the Linx part copies: + tabs at ±7.9 mm and the − contact is the round board pad under the cell, the same as the existing footprint, so no layout change. CR1216/1220/1225. |
| **U11** TUSB4041IPAPR | JLC has exactly 10. | **Kept.** Order promptly; no spare for losses. |
| **Module1** (two Amphenol 10164227-1001A1RLF) | One footprint and one reference for both connectors; JLC's placement file needs one entry per connector. | **Split:** Module1 = pins 1–100 (footprint `CM5_Connector_A`, which also carries the mounting holes and module outline), Module2 = pins 101–200 (`CM5_Connector_B`). Each footprint origin is its connector centre, so JLC gets one placement entry per connector. Same pads, nets and routing; no layout work needed. |
| **M2–M5** SMT nuts | No footprint in the design. | **Fitted by hand.** |
| **Y1** 24 MHz oscillator | ECS-2520MV-240-DN-TR: 0 at JLC. | **Switched to YXC OT252024MJBA4SL** (C669072, 4.5k at JLC). Checked in the YXC datasheet: pin 1 = tri-state, **enabled when high or floating** (Y1 pin 1 is unconnected), 2 GND, 3 OUT, 4 VDD as on the ECS part; 1.8–3.3 V supply (runs from +1V8), CMOS, ±20 ppm; 2520 land pattern matches the ECS footprint. Not at DigiKey, so Distributor = LCSC. |
| **J2** 2×7 header | Molex 0010897140: 0 at JLC. The Molex 0010897142 (C561778) chosen first has no footprint in JLC's library, so JLC's preview cannot show or place it (2026-10-12). | **Switched to a generic header: BOOMELE 2.54-2\*7P** (C71397, 21.5k at JLC, gold, $0.09). JLC's footprint matches ours pad for pad. 6 mm mating / 3 mm tail pins and a 2.5 mm insulator instead of the C-Grid's 6.1 / 2.8 mm and 2.29 mm. Not at DigiKey or Mouser, so Distributor = LCSC. |
| **J8** 40-pin header | Molex 0010897400: 0 at JLC. | **Switched to Würth 61304021121** (C5364405, 192 at JLC; DigiKey 732-5310-ND). Insulator 2.54 mm instead of 2.29 mm, so a HAT sits 0.25 mm higher. |
| **J22** HDMI | Molex 2086581051 (C5240402) has no footprint in JLC's library, and it was never checked against our footprint, which is the EDAC 690-019-298-412 from Raspberry Pi's CM5 IO board (2026-10-12). | **Switched to EDAC 690-019-298-412** (C5291558, 1,850 at JLC, $0.59), the part the footprint was drawn for and the one Raspberry Pi fits. JLC's footprint matches ours pad for pad. Not at DigiKey or Mouser, so Distributor = LCSC. |
| **SW1, SW2** buttons | C&K PTS645VH58-2 LFS: 0 at JLC. | **Switched to C&K PTS645VK39-2 LFS** (C285519, 6.5k at JLC; DigiKey CKN10053-ND). 3.85 mm actuator instead of 5.85 mm, 2.6 N instead of 2 N. Footprints set to KiCad's PTS645Vx39-2LFS (same pads as the Vx58/Vx31 ones used before, so routing stays); needs F8. |

## 2. Low stock to watch

| Part | JLC stock | Needed for 10 boards | Note |
|---|---|---|---|
| C3 A700X107M010ATE010 (100 µF polymer, 7343) | 31 | 10 | No other 7343 polymer at JLC meets 10 mΩ (closest is 15 mΩ). C57 changed to a 47 µF 1206 ceramic in `e869b1f`. |
| C20 A770KE396M1HLAS042 (39 µF, 50 V polymer) | 24 | 10 | Backup: KEMET A768KE396M1HLAE042 (C1517683), same specs. |
| J11 USB4105-GF-A (USB-C) | 39 | 10 | Same-series variants with -060/-120 suffixes have plenty of stock. |
| R50 158k 0603 | (exact part: 15) | 10 | Switched to UNI-ROYAL 0603WAF1583T5E (C22883, 52k in stock). |

## 3. JLC substitutions (passives and simple parts)

- **Resistors.**
  - 11 values use JLC **Basic/Preferred** UNI-ROYAL 0402WGF parts: same value, 1 %, ±100 ppm. They are
    rated 62.5 mW instead of Panasonic's 100 mW; this board's worst case is under 5 mW (the Ethernet LED
    resistors).
  - The four ERJ-U values (10k, 33k, 100k, 4.7k) lose Panasonic's anti-sulfur feature at JLC.
  - The 0603 resistors use Basic 100 mW parts.
  - E96 values without a Basic part keep the exact Panasonic part (extended).
- **Ceramic capacitors.**
  - Basic Samsung/Yageo/FH parts with the same or better voltage and dielectric. Several move from
    6.3 V or 10 V to 25 V.
  - C0G values stay C0G, and the 50 V input-rail parts stay 50 V.
- **Polymer capacitors.** These stay polymer.
  - C69 → Chemi-Con APXJ160ARA271MF80J: 270 µF, 16 V, 10 mΩ, 6.3 × 7.7 mm.
  - C51 → 22 µF, 50 V, 40 mΩ, rated 105 °C instead of 125 °C.
  - C26 (not fitted) → Panasonic 20SVPF56MX.
- **U1, U2 (Ethernet TVS, TPD4EUSB30): not fitted (DNP) from 2026-10-11.** The CM5 IO board, where they come from, labels them
  "Ethernet POE Protection"; LibreBoard has no PoE, and the MagJack already isolates the cable (1500 Vrms). The footprints stay:
  the lines run through under the chip, so the board works with them empty and they can be fitted later.
- **2N7002 (Q1, Q2):** CJ 2N7002 (C8545, Basic), standard SOT-23 pinout. **FB1:** Murata BLM15AG221SN1D (220 Ω, 0402).

## 4. DigiKey changes

- **Filled:**
  - J7 503398-1892 → `WM11190TR-ND`. It previously had a Farnell number, 2358234.
  - C61 → `490-3244-2-ND`.
  - C66–C68 → `445-6006-2-ND`.
  - Q1/Q2 → `2N7002-FDITR-ND`.
  - U20 → `LP38693MP-3.3/NOPBTR-ND`.
  - U21 → `296-48293-2-ND`.
  - C60 → `478-KGM05ACG1H6R8CHTR-ND`. AVX renamed 04025A6R8CAT2A to KGM05ACG1H6R8CH.
- **C72 changed part:** Murata GRM188R71C104KA01D is **obsolete**, and so are both Murata successors →
  Yageo **CC0603KRX7R9BB104** (`311-1344-2-ND`, LCSC C14663 Basic): 100 nF, 50 V, X7R, 0603.
- **U3 now from LCSC:** LINK-PP LPJG0926HENL is not sold by DigiKey, so U3's distributor is LCSC (C22457393) and the old DigiKey number 931-TMJG4926HENL-ND was removed from the schematic.
- **C73 wrong number:** `490-1494-2-ND` is a different (X7R, obsolete) part. The correct DigiKey number for
  GRM1885C1H102JA01D could not be looked up (the API failed), so the field will be **cleared — fill it by hand**.
  Mouser carries the part as 81-GRM39C102J50.
- **Small corrections:**
  - C27–C29: removed the trailing " - Cut Tape" from the number.
  - U9: distributor "LSCS" → "LCSC" (SK6812SIDE-A-RVS is not sold by DigiKey).
  - L2/L3: manufacturer Coilcraft → **Bourns** (SRN8040 is a Bourns part).
- **Out of stock at DigiKey:** TPS552892QWRYQRQ1 (and the TPS552892RYQR it replaced), 74LVC1G07SE-7,
  ASEK-32.768KHZ-L-R-T, AP3441SHE-7B.
- **Not at DigiKey (other distributor in the schematic):** U3, Y1, J2 and J22 (LCSC), U16 (LCSC; lookup failed).
- **Low stock at DigiKey:**
  - LI0402C221R-10: 1 in stock.
  - TLV75712PDBVR: 5.
  - 0805ZD106KAT2A (10 µF): 59 for 150 needed.
- **Reel numbers.** As you asked, the reel (TR) numbers were kept. Many have reel-size minimums
  (thousands), so for small DigiKey orders use the cut-tape (CT) version of the same part.

## 5. JLC cost estimate (10 boards)

- **Setup fees:** 60 unique extended parts × about $3 ≈ **$180 per order**, counting only parts JLC places
  (not the DNP or hand-fitted ones).
- **Parts:** about **$100 per board** at JLC's listed unit prices. This leaves out the parts in section 1
  without a JLC source, and the assembly and PCB charges.

## 6. Still open for rev3 (not sourcing)

- Layout after the 2026-10-11 part switches: run F8 (replace footprints) for U16 (SC-70-5, re-route) and
  SW1/SW2 (Vx39 outline, same pads).
