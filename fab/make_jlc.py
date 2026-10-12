#!/usr/bin/env python3
"""Generate the JLCPCB fabrication files for LibreBoard.

Writes to fab/rev3-jlc/ (or the directory given as the first argument):
  gerbers/                        13 Gerber layers + PTH/NPTH Excellon drill files
  libreboard-rev3-gerbers.zip     the same, zipped for upload
  libreboard-rev3-bom-jlc.csv     Comment, Designator, Footprint, LCSC Part #
  libreboard-rev3-cpl-jlc.csv     Designator, Mid X, Mid Y, Layer, Rotation

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

# JLC placement corrections, matched on the footprint name (regex), checked in JLC's placement preview.
#   centre: place at the centre of the footprint's numbered pads instead of the footprint origin.
#           JLC centres its part on the given point; KiCad puts pin 1 at the origin of these footprints.
#   rot:    degrees added to KiCad's rotation (JLC's library draws these parts turned by that much).
JLC_CORRECTIONS = [
    (r'^PinHeader_', {'centre': True, 'rot': 90}),             # J2, J3, J8: JLC drew J8 turned 90 deg and centred on pin 1
    (r'^CONN_SD-47053-001', {'centre': True, 'rot': 0}),       # J51-J54 fan headers: centred on pin 1
    (r'^CM5_Connector_[AB]$', {'rot': 90}),                    # Module1/2: JLC drew them across the footprint
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


def footprint_fields(board):
    """Reference -> (footprint name, LCSC, Value, centre of numbered pads in board mm or None) from the .kicad_pcb"""
    s = open(board, encoding='utf-8').read()
    out = {}
    for m in re.finditer(r'\n\t\(footprint "([^"]+)"', s):
        st = m.start() + 2
        blk = s[st:block_end(s, st)]
        props = dict(re.findall(r'\(property "([^"]+)" "((?:[^"\\]|\\.)*)"', blk))
        at = re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', blk)
        x0, y0, rot = float(at.group(1)), float(at.group(2)), math.radians(float(at.group(3) or 0))
        pads = [(float(x), float(y)) for x, y in re.findall(r'\(pad "[^"]+" \w+ \w+\s*\(at ([-\d.]+) ([-\d.]+)', blk)]
        centre = None
        if pads:
            cx = (min(p[0] for p in pads) + max(p[0] for p in pads)) / 2
            cy = (min(p[1] for p in pads) + max(p[1] for p in pads)) / 2
            # footprint frame -> board (KiCad: y down, angles counter-clockwise on screen)
            centre = (x0 + cx * math.cos(rot) + cy * math.sin(rot), y0 - cx * math.sin(rot) + cy * math.cos(rot))
        out[props['Reference']] = (m.group(1).split(':', 1)[-1], props.get('LCSC', '').strip(), props.get('Value', ''),
                                   centre)
    return out


def correction(footprint):
    for pattern, corr in JLC_CORRECTIONS:
        if re.search(pattern, footprint):
            return corr
    return {}


def natural(ref):
    m = re.match(r'([A-Za-z]+)(\d+)', ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


def ascii_value(v):
    return v.replace('µ', 'u').replace('Ω', '').replace('±', '+/-').replace('°', 'deg')


def main():
    gdir = os.path.join(OUT, 'gerbers')
    os.makedirs(gdir, exist_ok=True)
    for f in os.listdir(gdir):
        os.remove(os.path.join(gdir, f))
    # JLC's recommended KiCad settings: Protel extensions, no X2/netlist attributes,
    # soldermask subtracted from silkscreen, 4.6 mm format; Excellon mm, decimal,
    # absolute origin, separate PTH/NPTH, alternate oval-hole mode.
    cli('pcb', 'export', 'gerbers', '--layers', LAYERS, '--no-x2', '--no-netlist', '--subtract-soldermask',
        '--precision', '6', '-o', gdir + os.sep, BOARD)
    cli('pcb', 'export', 'drill', '--format', 'excellon', '--drill-origin', 'absolute',
        '--excellon-zeros-format', 'decimal', '--excellon-oval-format', 'alternate', '--excellon-separate-th',
        '--excellon-units', 'mm', '-o', gdir + os.sep, BOARD)
    for f in os.listdir(gdir):
        if f.endswith('.gbrjob'):
            os.remove(os.path.join(gdir, f))
    with zipfile.ZipFile(os.path.join(OUT, 'libreboard-rev3-gerbers.zip'), 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(gdir)):
            z.write(os.path.join(gdir, f), f)

    with tempfile.TemporaryDirectory() as td:
        pos = os.path.join(td, 'pos.csv')
        cli('pcb', 'export', 'pos', '--format', 'csv', '--units', 'mm', '--exclude-dnp', '-o', pos, BOARD)
        rows = list(csv.DictReader(open(pos, encoding='utf-8')))
    fields = footprint_fields(BOARD)
    placed = [r for r in rows if fields[r['Ref']][1]]
    skipped = sorted({r['Ref'] for r in rows} - {r['Ref'] for r in placed}, key=natural)

    with open(os.path.join(OUT, 'libreboard-rev3-cpl-jlc.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['Designator', 'Mid X', 'Mid Y', 'Layer', 'Rotation'])
        for r in sorted(placed, key=lambda r: natural(r['Ref'])):
            name, _, _, centre = fields[r['Ref']]
            corr = correction(name)
            x, y = float(r['PosX']), float(r['PosY'])
            if corr.get('centre') and centre:
                x, y = centre[0], -centre[1]          # position export uses y up
            rot = (float(r['Rot']) + corr.get('rot', 0)) % 360
            w.writerow([r['Ref'], f"{x:.4f}mm", f"{y:.4f}mm", 'Top' if r['Side'] == 'top' else 'Bottom', f"{rot:g}"])

    groups = collections.OrderedDict()
    for r in sorted(placed, key=lambda r: natural(r['Ref'])):
        groups.setdefault(fields[r['Ref']][1], []).append(r['Ref'])
    with open(os.path.join(OUT, 'libreboard-rev3-bom-jlc.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['Comment', 'Designator', 'Footprint', 'LCSC Part #'])
        for lcsc, refs in groups.items():
            values = collections.Counter(ascii_value(fields[x][2]) for x in refs)
            comment = values.most_common(1)[0][0]
            if len(values) > 1 and all(v.startswith('12V Fan') for v in values):
                comment = '12V Fan'
            names = ' / '.join(sorted({fields[x][0] for x in refs}))
            w.writerow([comment, ','.join(refs), names, lcsc])

    print(f'{OUT}: {len(os.listdir(gdir))} Gerber/drill files, {len(placed)} placed parts, '
          f'{len(groups)} BOM lines; left out (no LCSC): {", ".join(skipped) or "none"}')


if __name__ == '__main__':
    main()
