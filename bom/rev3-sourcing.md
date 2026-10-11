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
- **Schematic not written yet.** These values still have to go into the schematic (new hidden `LCSC`
  field, plus DigiKey fixes). That waits until KiCad is closed: the schematic editor was open overnight.
  The change has been rehearsed on a copy of the project:
  - 189 parts edited, 219 field values checked;
  - connectivity, values and footprints identical;
  - ERC unchanged at 342.

## 1. Decisions needed before ordering at JLC

| # | Part | Problem | Options |
|---|---|---|---|
| 1 | **U4, U14** TPS552892RYQR (self-starting buck-boost) | **Not available anywhere:** JLC 1, DigiKey 0, Mouser 0. | **Recommended:** switch to **TPS552892QWRYQRQ1**, the automotive (AEC-Q100) version. It is a drop-in: all 21 pins, the RYQ package, VREF 1.2 V and the 3–36 V input range compared identical between the two TI datasheets. Stock: Mouser **25**, JLC 5 (LCSC C22375748), DigiKey 0. Buy 20 at Mouser and have JLC use them, or build fewer boards. |
| 2 | **U17** TCA9538DBR (I/O expander) | JLC has 1. | Buy from DigiKey (21k in stock) and supply it to JLC, or use JLC's parts-sourcing from DigiKey. No same-footprint alternative is in stock. |
| 3 | **U16** SN74AHCT1G125DRLR (LED buffer, SOT-553) | JLC has 0. | Supply from DigiKey (5.4k), **or** change the footprint to SC-70-5 (SN74AHCT1G125DCKR, C350557, 16k at JLC) or SOT-23-5 (DBVR, C7484, 45k). The pinout is the same; only the footprint changes. |
| 4 | **U3** TMJG4926HENL (MagJack, through-hole) | JLC 0; DigiKey only 4. | Buy elsewhere and supply it, or choose another MagJack. This is also the part with the broken pin-10 winding on your Rev1 board. |
| 5 | **BT1** BAT-HLD-007-SMT-TR (coin-cell holder) | JLC 0. | Supply from DigiKey (4.1k), or change to a holder JLC stocks (needs a footprint change). |
| 6 | **U11** TUSB4041IPAPR (USB hub) | JLC has exactly 10, with no spare for losses. | Order quickly, or supply 2–3 spares from DigiKey (141 in stock). |
| 7 | **Module1** (two CM5 connectors, Amphenol 10164227-1001A1RLF) | Both connectors sit in **one** footprint with one reference, but JLC's placement file needs one entry per connector. | Split it into two footprints/references (for example J9A/J9B), or give JLC separate coordinates for each. LCSC C6782225, 2 per board. |
| 8 | **M2–M5** SMT nuts (LCSC C2916320) | They have no footprint in the design, so JLC can't place them. | Add a footprint if they should be machine-placed. Otherwise fit them by hand. The M1 screw is never assembled. |

### Parts needing your review (no LCSC code stored yet)

| Refs | Original | JLC candidate | What to check |
|---|---|---|---|
| **Y1** | ECS-2520MV-240-DN-TR (exact part 0 at JLC) | YXC **OT252024MJBA4SL**, C669072 (24 MHz CMOS, 1.8–3.3 V, ±20 ppm, 2520 4-pin, 4.5k in stock) | Pin 1 must be an enable pin that is **on when left unconnected**: Y1 pin 1 is no-connect on the board, and Y1 runs from **1.8 V**. |
| **J2** (2×7 header) | Molex 0010897140 (0 at JLC) | Molex 10897142, C561778. Second choice: Würth 61301421121, C5162129 | Different suffix in the same series; check plating and pin lengths. |
| **J8** (40-pin header) | Molex 0010897400 (0 at JLC) | Würth 61304021121, C5364405 (192 in stock) | Plastic body is 0.25 mm taller, which raises a HAT slightly. |
| **SW1, SW2** | C&K PTS645VH58-2 LFS (0 at JLC) | C&K PTS645VK392LFS, C285519 | Shorter actuator and a stiffer press (2.6 N vs 2 N). Check how far the buttons reach at the board edge. |

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
- **C73 wrong number:** `490-1494-2-ND` is a different (X7R, obsolete) part. The correct DigiKey number for
  GRM1885C1H102JA01D could not be looked up (the API failed), so the field will be **cleared — fill it by hand**.
  Mouser carries the part as 81-GRM39C102J50.
- **Small corrections:**
  - C27–C29: removed the trailing " - Cut Tape" from the number.
  - U9: distributor "LSCS" → "LCSC" (SK6812SIDE-A-RVS is not sold by DigiKey).
  - L2/L3: manufacturer Coilcraft → **Bourns** (SRN8040 is a Bourns part).
- **Out of stock at DigiKey:** TPS552892RYQR, 74LVC1G07SE-7, ASEK-32.768KHZ-L-R-T, AP3441SHE-7B.
- **Low stock at DigiKey:**
  - LI0402C221R-10: 1 in stock.
  - TMJG4926HENL: 4.
  - TLV75712PDBVR: 5.
  - 0805ZD106KAT2A (10 µF): 59 for 150 needed.
- **Reel numbers.** As you asked, the reel (TR) numbers were kept. Many have reel-size minimums
  (thousands), so for small DigiKey orders use the cut-tape (CT) version of the same part.

## 5. JLC cost estimate (10 boards)

- **Setup fees:** 61 unique extended parts × about $3 ≈ **$183 per order**.
- **Parts:** about **$100 per board** at JLC's listed unit prices. This leaves out the parts in section 1
  without a JLC source, and the assembly and PCB charges.

## 6. Still open for rev3 (not sourcing)

- Route J15 / U21: HD3SS3220 placed, not routed.
- Apply the fields above once KiCad is closed (rehearsed, about a minute), then commit.
