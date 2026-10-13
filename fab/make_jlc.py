#!/usr/bin/env python3
"""Generate the JLCPCB fabrication files for LibreBoard.

Writes to fab/rev3-jlc/ (or the directory given as the first argument):
  gerbers/                        13 Gerber layers + PTH/NPTH Excellon drill files
  libreboard-rev3-gerbers.zip     the same, zipped for upload
  libreboard-rev3-bom-jlc.csv     Comment, Designator, Footprint, LCSC Part #
  libreboard-rev3-cpl-jlc.csv     Designator, Mid X, Mid Y, Layer, Rotation
  libreboard-rev3-{bom,cpl}-jlc-smt-only.csv
                                  the same without the through-hole parts (every numbered pad plated
                                  through), for buying and soldering those by hand
  libreboard-rev3-tht-hand-fit.csv
                                  those through-hole parts with their order fields and solder joints

Parts are taken from the board's placement export: DNP footprints and footprints marked
"exclude from position files" (e.g. hand-fitted U17) are left out, and so is anything
without an LCSC field (fiducials). BOM lines are grouped by LCSC number.

Set KICAD_CLI if kicad-cli is not at the default location.
"""
import collections
import math
import csv
import os
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(ROOT, 'libreboard.kicad_pcb')
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, 'fab', 'rev3-jlc')
KICAD_CLI = os.environ.get('KICAD_CLI') or (
    '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli' if sys.platform == 'darwin' else 'kicad-cli')
LAYERS = 'F.Cu,In1.Cu,In2.Cu,In3.Cu,In4.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts'

# JLC placement corrections.
# 1. fab/jlc-corrections.csv (written by fab/jlc_fit.py from JLC's own EasyEDA footprints): per LCSC number
#    and KiCad footprint, the rotation to add and where JLC's footprint origin lies in our footprint's frame.
# 2. For parts without a usable entry there (JLC has no footprint for J2, or the file is missing), this
#    fallback table (regex on the footprint name), taken from the fits of similar parts:
#      centre: place at the centre of the numbered pads instead of the footprint origin;
#      rot:    degrees added to KiCad's rotation.
CORRECTIONS_CSV = os.path.join(ROOT, 'fab', 'jlc-corrections.csv')
FALLBACK_CORRECTIONS = [
    (r'^PinHeader_', {'centre': True, 'rot': 270}),            # as fitted for J3 and J8
    (r'^CONN_SD-47053-001', {'centre': True, 'rot': 0}),       # J51-J54 fan headers
    (r'^CM5_Connector_[AB]$', {'rot': 270}),                   # Module1/2
]


def cli(*args):
    subprocess.run([KICAD_CLI, *args], check=True, capture_output=True)


def block_end(s, start):
    """index just past the s-expression that opens at s[start] == '('"""
    depth, i, in_str = 0, start, False
    while i < len(s):
        c = s[i]
        if in_str:
            if c == '\\':
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError('unbalanced s-expression')


def rotate(x, y, deg):
    """footprint frame -> board offset (KiCad: y down, angles counter-clockwise on screen)"""
    a = math.radians(deg)
    return x * math.cos(a) + y * math.sin(a), -x * math.sin(a) + y * math.cos(a)


def footprint_fields(board):
    """Reference -> dict(name, lcsc, value, x, y, rot, centre, tht, joints, props) from the .kicad_pcb;
    centre = centre of the numbered pads in the footprint's own frame, tht = every numbered pad is plated
    through (a part with SMD pins and through-hole shell stakes is not), joints = plated through-hole pads"""
    s = open(board, encoding='utf-8').read()
    out = {}
    for m in re.finditer(r'\n\t\(footprint "([^"]+)"', s):
        st = m.start() + 2
        blk = s[st:block_end(s, st)]
        props = dict(re.findall(r'\(property "([^"]+)" "((?:[^"\\]|\\.)*)"', blk))
        at = re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', blk)
        pads = [(float(x), float(y)) for x, y in re.findall(r'\(pad "[^"]+" \w+ \w+\s*\(at ([-\d.]+) ([-\d.]+)', blk)]
        types = re.findall(r'\(pad "([^"]*)" (\w+)', blk)
        numbered = {t for n, t in types if n}
        centre = None
        if pads:
            centre = ((min(p[0] for p in pads) + max(p[0] for p in pads)) / 2,
                      (min(p[1] for p in pads) + max(p[1] for p in pads)) / 2)
        out[props['Reference']] = dict(name=m.group(1).split(':', 1)[-1], lcsc=props.get('LCSC', '').strip(),
                                       value=props.get('Value', ''), x=float(at.group(1)), y=float(at.group(2)),
                                       rot=float(at.group(3) or 0), centre=centre,
                                       tht=numbered == {'thru_hole'}, joints=sum(t == 'thru_hole' for _, t in types),
                                       props=props)
    return out


def load_corrections():
    """(lcsc, footprint) -> (rotation to add, dx, dy) for entries jlc_fit.py marked ok (or added by hand)"""
    out = {}
    if os.path.exists(CORRECTIONS_CSV):
        for r in csv.DictReader(open(CORRECTIONS_CSV, encoding='utf-8')):
            if r.get('status') in ('ok', 'manual'):
                out[(r['lcsc'], r['footprint'])] = (float(r['rotation']), float(r['dx']), float(r['dy']))
    return out


def fallback(footprint):
    for pattern, corr in FALLBACK_CORRECTIONS:
        if re.search(pattern, footprint):
            return corr
    return {}


def placement(f, corrections):
    """(x, y, rotation) for JLC's placement file, y up as in KiCad's position export"""
    c = corrections.get((f['lcsc'], f['name']))
    if c:
        rot_add, dx, dy = c
    else:
        corr = fallback(f['name'])
        rot_add = corr.get('rot', 0)
        dx, dy = f['centre'] if corr.get('centre') and f['centre'] else (0.0, 0.0)
    ox, oy = rotate(dx, dy, f['rot'])
    return f['x'] + ox, -(f['y'] + oy), (f['rot'] + rot_add) % 360


def position_rows():
    with tempfile.TemporaryDirectory() as td:
        pos = os.path.join(td, 'pos.csv')
        cli('pcb', 'export', 'pos', '--format', 'csv', '--units', 'mm', '--exclude-dnp', '-o', pos, BOARD)
        return list(csv.DictReader(open(pos, encoding='utf-8')))


def placed_refs():
    """references JLC places: in the position export (no DNP, not excluded) and with an LCSC number"""
    fields = footprint_fields(BOARD)
    return sorted((r['Ref'] for r in position_rows() if fields[r['Ref']]['lcsc']), key=natural)


def natural(ref):
    m = re.match(r'([A-Za-z]+)(\d+)', ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


def ascii_value(v):
    return v.replace('µ', 'u').replace('Ω', '').replace('±', '+/-').replace('°', 'deg')


def undated(path):
    """lines of a Gerber/drill file without the ones that only carry the export date"""
    with open(path, encoding='utf-8', errors='replace') as f:
        return [line for line in f if 'CreationDate' not in line and not re.search(r' date \d{4}-\d\d-\d\d', line)]


def write_bom_cpl(rows, fields, corrections, suffix):
    """JLC placement file and BOM for these position-export rows; returns the number of BOM lines"""
    with open(os.path.join(OUT, f'libreboard-rev3-cpl-jlc{suffix}.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['Designator', 'Mid X', 'Mid Y', 'Layer', 'Rotation'])
        for r in sorted(rows, key=lambda r: natural(r['Ref'])):
            x, y, rot = placement(fields[r['Ref']], corrections)
            w.writerow([r['Ref'], f"{x:.4f}mm", f"{y:.4f}mm", 'Top' if r['Side'] == 'top' else 'Bottom', f"{rot:g}"])

    groups = collections.OrderedDict()
    for r in sorted(rows, key=lambda r: natural(r['Ref'])):
        groups.setdefault(fields[r['Ref']]['lcsc'], []).append(r['Ref'])
    with open(os.path.join(OUT, f'libreboard-rev3-bom-jlc{suffix}.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['Comment', 'Designator', 'Footprint', 'LCSC Part #'])
        for lcsc, refs in groups.items():
            names = ' / '.join(sorted({fields[x]['name'] for x in refs}))
            w.writerow([group_value(refs, fields), ','.join(refs), names, lcsc])
    return len(groups)


def group_value(refs, fields):
    """one value for a BOM line: the most common one ('12V Fan 1'..'4' -> '12V Fan')"""
    values = collections.Counter(ascii_value(fields[x]['value']) for x in refs)
    if len(values) > 1 and all(v.startswith('12V Fan') for v in values):
        return '12V Fan'
    return values.most_common(1)[0][0]


def main():
    gdir = os.path.join(OUT, 'gerbers')
    os.makedirs(gdir, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        # JLC's recommended KiCad settings: Protel extensions, no X2/netlist attributes,
        # soldermask subtracted from silkscreen, 4.6 mm format; Excellon mm, decimal,
        # absolute origin, separate PTH/NPTH, alternate oval-hole mode.
        cli('pcb', 'export', 'gerbers', '--layers', LAYERS, '--no-x2', '--no-netlist', '--subtract-soldermask',
            '--precision', '6', '-o', td + os.sep, BOARD)
        cli('pcb', 'export', 'drill', '--format', 'excellon', '--drill-origin', 'absolute',
            '--excellon-zeros-format', 'decimal', '--excellon-oval-format', 'alternate', '--excellon-separate-th',
            '--excellon-units', 'mm', '-o', td + os.sep, BOARD)
        new = {f for f in os.listdir(td) if not f.endswith('.gbrjob')}
        for f in set(os.listdir(gdir)) - new:
            os.remove(os.path.join(gdir, f))
        for f in new:
            # keep files whose only change is the export date, so a re-run does not touch them in git
            old = os.path.join(gdir, f)
            if not os.path.exists(old) or undated(old) != undated(os.path.join(td, f)):
                os.replace(os.path.join(td, f), old)
    with zipfile.ZipFile(os.path.join(OUT, 'libreboard-rev3-gerbers.zip'), 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(gdir)):
            z.write(os.path.join(gdir, f), f)

    rows = position_rows()
    fields = footprint_fields(BOARD)
    corrections = load_corrections()
    placed = [r for r in rows if fields[r['Ref']]['lcsc']]
    skipped = sorted({r['Ref'] for r in rows} - {r['Ref'] for r in placed}, key=natural)

    lines = write_bom_cpl(placed, fields, corrections, '')
    # Through-hole parts left out: bought and soldered by hand. Parts with SMD pins and through-hole shell
    # stakes or pegs (USB-C J11/J15, HDMI J22, M.2 J4) stay with JLC: they need paste and reflow.
    smt = [r for r in placed if not fields[r['Ref']]['tht']]
    tht = [r for r in placed if fields[r['Ref']]['tht']]
    smt_lines = write_bom_cpl(smt, fields, corrections, '-smt-only')
    hand = collections.OrderedDict()
    for r in sorted(tht, key=lambda r: natural(r['Ref'])):
        p = fields[r['Ref']]['props']
        hand.setdefault((p.get('Manufacturer', ''), p.get('Manf. P/N', '')), []).append(r['Ref'])
    with open(os.path.join(OUT, 'libreboard-rev3-tht-hand-fit.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['Designator', 'Qty', 'Value', 'Manufacturer', 'Manf. P/N', 'Distributor', 'Dist. P/N', 'LCSC',
                    'Solder joints'])
        for (manf, mpn), refs in hand.items():
            p = fields[refs[0]]['props']
            w.writerow([','.join(refs), len(refs), group_value(refs, fields), manf, mpn, p.get('Distributor', ''),
                        p.get('Dist. P/N', ''), p.get('LCSC', ''), sum(fields[x]['joints'] for x in refs)])

    print(f'{OUT}: {len(os.listdir(gdir))} Gerber/drill files, {len(placed)} placed parts, '
          f'{lines} BOM lines; left out (no LCSC): {", ".join(skipped) or "none"}')
    print(f'SMT only: {len(smt)} parts, {smt_lines} BOM lines; by hand: {len(tht)} through-hole parts '
          f'({", ".join(sorted((r["Ref"] for r in tht), key=natural))}), '
          f'{sum(fields[r["Ref"]]["joints"] for r in tht)} solder joints per board')


if __name__ == '__main__':
    main()
