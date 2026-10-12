#!/usr/bin/env python3
"""Work out JLCPCB placement corrections from JLC's own footprints.

JLC places every part from its EasyEDA footprint (JLCEDA/EasyEDA official library, https://easyeda.com,
https://lceda.cn): the placement-file point is that footprint's origin and rotation 0 is that footprint's
orientation. Our KiCad footprints often differ (pin 1 as origin, parts drawn turned by 90/180/270 deg).

For every part JLC places (same selection as make_jlc.py), this script downloads the EasyEDA footprint of
its LCSC number and fits its pads onto ours:
  - by pad number where both libraries number the pads the same way;
  - by position where the numbering differs, for two-pad resistors, capacitors and inductors (whose pads
    are interchangeable), and where the numbered fit leaves one of JLC's pads (e.g. a mounting tab) away
    from all of ours: then the two libraries number the pins differently and the pads decide.
The offset is the midpoint of the smallest and largest pad mismatch, so longer (hand-soldering) pads on
one side do not pull it off centre.
When several rotations fit equally well (symmetric pad patterns) and they connect the same nets, the part
body decides if it can: the rotation that lines JLC's body outline up with our F.Fab outline wins. If the
nets differ, the entry is marked ambiguous and make_jlc.py ignores it.

Writes fab/jlc-corrections.csv: per LCSC number and KiCad footprint, the rotation to add and the offset of
JLC's origin in our footprint's frame, plus the fit quality. body_mm is the distance between JLC's body
centre and ours after the correction and worst_mm how far the JLC pad furthest from any of ours lands
(large values deserve a look in JLC's preview). make_jlc.py applies the file; it needs no network.

Downloads are cached in fab/.easyeda-cache/ (git-ignored) and paced (one request every DELAY seconds;
when the server refuses, wait and retry).

usage: python3 fab/jlc_fit.py [--offline]     (--offline: use the cache only, skip parts not in it)
"""
import csv
import json
import math
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_jlc  # noqa: E402

ROOT = make_jlc.ROOT
CACHE = os.path.join(ROOT, 'fab', '.easyeda-cache')
OUT = os.path.join(ROOT, 'fab', 'jlc-corrections.csv')
DELAY, RETRY_WAIT, MAX_WAIT = 20, 300, 10 * 3600
UNIT = 0.254  # EasyEDA coordinate unit (10 mil) in mm
TIE = 0.05    # rotations whose pad fits are within this (mm rms) of the best one are equally good
BODY = 0.3    # the body outline breaks a tie only if it fits this much (mm) better
STRAY = 1.0   # a JLC pad this far (mm) from all of ours means the pad numbers do not tell the orientation


def fetch(lcsc, offline=False):
    """EasyEDA package of an LCSC number, None if JLC has no footprint (or, offline, if not cached)"""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, lcsc + '.json')
    if not os.path.exists(path):
        if offline:
            return None
        start = time.time()
        while True:
            r = subprocess.run(['curl', '-s', '-m', '30',
                                f'https://easyeda.com/api/products/{lcsc}/components?version=6.4.19.5'],
                               capture_output=True, text=True)
            if r.stdout.startswith('{'):
                open(path, 'w').write(r.stdout)
                time.sleep(DELAY)
                break
            if time.time() - start > MAX_WAIT:
                return None
            print(f'  {lcsc}: request refused, retrying in {RETRY_WAIT} s', flush=True)
            time.sleep(RETRY_WAIT)
    try:
        return json.load(open(path))['result']['packageDetail']
    except (KeyError, TypeError, ValueError):
        return None


def rot(x, y, deg):
    a = math.radians(deg)
    return x * math.cos(a) + y * math.sin(a), -x * math.sin(a) + y * math.cos(a)


def bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def centre(pts):
    x0, y0, x1, y1 = bbox(pts)
    return (x0 + x1) / 2, (y0 + y1) / 2


# --- JLC (EasyEDA) footprints ------------------------------------------------------------------------------

def path_points(d):
    """end points of an SVG-style path (M/L/A commands), in EasyEDA units"""
    tok = re.findall(r'[MLAZ]|[-\d.]+', d)
    pts, i, cmd = [], 0, None
    while i < len(tok):
        if tok[i] in 'MLAZ':
            cmd = tok[i]
            i += 1
            continue
        if cmd == 'A':
            pts.append((float(tok[i + 5]), float(tok[i + 6])))
            i += 7
        else:
            pts.append((float(tok[i]), float(tok[i + 1])))
            i += 2
    return pts


def jlc_footprint(pkg):
    """(pads [(number, x, y)], body points) in mm relative to the footprint origin, y down"""
    ds = pkg['dataStr']
    hx, hy = float(ds['head']['x']), float(ds['head']['y'])
    mm = lambda x, y: ((x - hx) * UNIT, (y - hy) * UNIT)  # noqa: E731
    pads, body = [], {'99': [], '3': []}   # 99: component outline, 3: top silkscreen
    for s in ds['shape']:
        f = s.split('~')
        if f[0] == 'PAD':
            pads.append((f[8].strip(), *mm(float(f[2]), float(f[3]))))
        elif f[0] == 'TRACK' and f[2] in body:
            v = [float(n) for n in f[4].split()]
            body[f[2]] += [mm(v[i], v[i + 1]) for i in range(0, len(v) - 1, 2)]
        elif f[0] == 'SOLIDREGION' and f[1] in body:
            body[f[1]] += [mm(x, y) for x, y in path_points(f[3])]
        elif f[0] == 'CIRCLE' and f[5] in body:
            cx, cy, r = float(f[1]), float(f[2]), float(f[3])
            body[f[5]] += [mm(cx - r, cy - r), mm(cx + r, cy + r)]
    return pads, body['99'] or body['3']


# --- our footprints ---------------------------------------------------------------------------------------

def outline(blk, layer):
    """points of the footprint graphics on one layer, in the footprint's own frame"""
    pts = []
    for g in re.finditer(r'\(fp_(line|rect|poly|circle|arc)\b', blk):
        gb = blk[g.start():make_jlc.block_end(blk, g.start())]
        if f'(layer "{layer}")' not in gb:
            continue
        p = [(float(x), float(y)) for x, y in re.findall(r'\((?:start|end|mid|center|xy) ([-\d.]+) ([-\d.]+)\)', gb)]
        if g.group(1) == 'circle':
            (cx, cy), (ex, ey) = p
            r = math.hypot(ex - cx, ey - cy)
            p = [(cx - r, cy - r), (cx + r, cy + r)]
        pts += p
    return pts


def board_footprints():
    """Reference -> dict(name, lcsc, pads [(number, x, y, net)], body points), footprint frame; mechanical
    pads without a number are included with number ''"""
    s = open(make_jlc.BOARD, encoding='utf-8').read()
    out = {}
    for m in re.finditer(r'\n\t\(footprint "([^"]+)"', s):
        st = m.start() + 2
        blk = s[st:make_jlc.block_end(s, st)]
        props = dict(re.findall(r'\(property "([^"]+)" "((?:[^"\\]|\\.)*)"', blk))
        pads = []
        for p in re.finditer(r'\(pad "([^"]*)" ', blk):
            pb = blk[p.start():make_jlc.block_end(blk, p.start())]
            at = re.search(r'\(at ([-\d.]+) ([-\d.]+)', pb)
            net = re.search(r'\(net (?:\d+ )?"([^"]*)"', pb)
            pads.append((p.group(1), float(at.group(1)), float(at.group(2)), net.group(1) if net else ''))
        out[props['Reference']] = dict(name=m.group(1).split(':', 1)[-1], lcsc=props.get('LCSC', '').strip(),
                                       pads=pads, body=outline(blk, 'F.Fab') or outline(blk, 'F.CrtYd'))
    return out


# --- fitting -----------------------------------------------------------------------------------------------

def fit_numbers(kp, jp):
    """[(rms, rotation, tx, ty)] best first, and the number of pads matched; None if the numbers differ"""
    kd, jd = {}, {}
    for n, x, y, _ in kp:
        kd.setdefault(n, []).append((x, y))
    for n, x, y in jp:
        jd.setdefault(n, []).append((x, y))
    common = [n for n in kd if n in jd and len(kd[n]) == 1 and len(jd[n]) == 1]
    if len(common) < 2:
        # e.g. Module2: our pads 101-200, JLC's 1-100
        try:
            shift = min(int(n) for n in kd if n.isdigit()) - min(int(n) for n in jd if n.isdigit())
        except ValueError:
            shift = 0
        if shift:
            jd = {str(int(n) + shift) if n.isdigit() else n: v for n, v in jd.items()}
            common = [n for n in kd if n in jd and len(kd[n]) == 1 and len(jd[n]) == 1]
    if len(common) < 2:
        return None
    fits = []
    for th in (0, 90, 180, 270):
        fits.append(midrange([(kd[n][0], rot(*jd[n][0], th)) for n in common], th))
    fits.sort()
    return fits, len(common)


def midrange(pairs, th):
    """(rms, th, tx, ty) for (our pad, JLC pad) pairs: the offset halfway between the smallest and largest
    mismatch in x and in y"""
    dx = [k[0] - j[0] for k, j in pairs]
    dy = [k[1] - j[1] for k, j in pairs]
    tx, ty = (min(dx) + max(dx)) / 2, (min(dy) + max(dy)) / 2
    rms = math.sqrt(sum((a - tx) ** 2 + (b - ty) ** 2 for a, b in zip(dx, dy)) / len(dx))
    return rms, th, tx, ty


def fit_geometry(kp, jp):
    """[(rms, rotation, tx, ty)] best first: nearest-pad fit of the pad positions, numbers ignored"""
    kpts = [(x, y) for _, x, y, _ in kp]
    fits = []
    for th in (0, 90, 180, 270):
        jpts = [rot(x, y, th) for _, x, y in jp]
        tx = sum(p[0] for p in kpts) / len(kpts) - sum(p[0] for p in jpts) / len(jpts)
        ty = sum(p[1] for p in kpts) / len(kpts) - sum(p[1] for p in jpts) / len(jpts)
        for _ in range(6):
            dx = dy = err = 0
            for qx, qy in jpts:
                qx, qy = qx + tx, qy + ty
                k = min(kpts, key=lambda p: (p[0] - qx) ** 2 + (p[1] - qy) ** 2)
                dx += k[0] - qx
                dy += k[1] - qy
                err += (k[0] - qx) ** 2 + (k[1] - qy) ** 2
            tx += dx / len(jpts)
            ty += dy / len(jpts)
        pairs = [(min(kpts, key=lambda p: (p[0] - qx - tx) ** 2 + (p[1] - qy - ty) ** 2), (qx, qy)) for qx, qy in jpts]
        fits.append(midrange(pairs, th))
    fits.sort()
    return fits


def nets_under(fit, kp, jp):
    """net of our pad nearest to each of JLC's pads, with JLC's footprint placed by this fit"""
    _, th, tx, ty = fit
    out = []
    for _, x, y in jp:
        qx, qy = rot(x, y, th)
        out.append(min(kp, key=lambda p: (p[1] - qx - tx) ** 2 + (p[2] - qy - ty) ** 2)[3])
    return out


def worst_pad(fit, kp, jp):
    """distance (mm) from the JLC pad furthest from any of ours to our nearest pad"""
    _, th, tx, ty = fit
    placed = [rot(x, y, th) for _, x, y in jp]
    return max(min(math.hypot(p[1] - qx - tx, p[2] - qy - ty) for p in kp) for qx, qy in placed)


def body_offset(fit, kbody, jbody):
    """distance (mm) between our body centre and JLC's, JLC's footprint placed by this fit"""
    if not kbody or not jbody:
        return None
    _, th, tx, ty = fit
    jx, jy = centre([rot(x, y, th) for x, y in jbody])
    kx, ky = centre(kbody)
    return math.hypot(jx + tx - kx, jy + ty - ky)


def choose(fits, kp, jp, kbody, jbody, interchangeable):
    """(fit, status, note) from fits sorted best first"""
    tied = [f for f in fits if f[0] - fits[0][0] < TIE]
    best, note = fits[0], ''
    if len(tied) > 1:
        same = interchangeable or all(nets_under(f, kp, jp) == nets_under(tied[0], kp, jp) for f in tied)
        if not same:
            return best, 'ambiguous', 'rotations ' + '/'.join(str(f[1]) for f in tied) + ' fit equally'
        best = min(tied, key=lambda f: f[1])
        note = 'symmetric pads'
        if kbody and jbody:
            by_body = sorted(tied, key=lambda f: body_offset(f, kbody, jbody))
            if body_offset(by_body[1], kbody, jbody) - body_offset(by_body[0], kbody, jbody) >= BODY:
                best, note = by_body[0], 'symmetric pads, body outline decides'
    rest = [f[0] for f in fits if f not in tied]
    clear = not rest or min(rest) - best[0] > 1.0
    status = 'ok' if best[0] < 0.25 or (best[0] < 0.6 and clear) else 'poor fit'
    if status == 'ok' and best[0] >= 0.25:
        note = note or 'pad sizes differ, rotation is clear'
    return best, status, note


def main():
    offline = '--offline' in sys.argv[1:]
    fps = board_footprints()
    groups = {}
    for ref in make_jlc.placed_refs():
        if fps[ref]['lcsc']:
            groups.setdefault((fps[ref]['lcsc'], fps[ref]['name']), []).append(ref)

    rows = []
    for (lcsc, name), refs in sorted(groups.items(), key=lambda kv: make_jlc.natural(kv[1][0])):
        row = dict(lcsc=lcsc, footprint=name, refs=' '.join(refs))
        pkg = fetch(lcsc, offline)
        if not pkg:
            missing = not os.path.exists(os.path.join(CACHE, lcsc + '.json'))
            rows.append(dict(row, status='not cached' if missing else 'no JLC footprint'))
            print(f'{",".join(refs)}: {rows[-1]["status"]}', flush=True)
            continue
        jp, jbody = jlc_footprint(pkg)
        fp = fps[refs[0]]
        kp, kbody = fp['pads'], fp['body']
        # two-pad resistors, capacitors, inductors and beads: either pad may go either way
        interchangeable = len(kp) == 2 and re.match(r'^(R|L|FB|C)\d', refs[0]) and not name.startswith('CP_')
        num = None if interchangeable else fit_numbers(kp, jp)
        geo = fit_geometry(kp, jp)
        method, fits, matched = 'numbers', None, 0
        if num:
            fits, matched = num
        if not fits or (fits[0][0] > 0.25 and geo[0][0] < 0.1):
            method, fits, matched = 'geometry', geo, len(jp)
        fit, status, note = choose(fits, kp, jp, kbody, jbody, interchangeable)
        if method == 'numbers' and worst_pad(fit, kp, jp) > STRAY:
            gfit, gstatus, gnote = choose(geo, kp, jp, kbody, jbody, interchangeable)
            if gstatus == 'ok' and worst_pad(gfit, kp, jp) <= STRAY:
                note = f'pin numbers differ from JLC\'s (by number it would be +{fit[1]}); placed by pad positions'
                method, fit, status, matched = 'geometry', gfit, gstatus, len(jp)
            else:
                status, note = 'poor fit', 'some JLC pads land off ours'
        rms, th, tx, ty = fit
        tx, ty = round(tx, 3) + 0, round(ty, 3) + 0   # + 0: no "-0.000"
        bo = body_offset(fit, kbody, jbody)
        rows.append(dict(row, jlc_footprint=pkg.get('title', ''), rotation=th, dx=f'{tx:.3f}', dy=f'{ty:.3f}',
                         method=method, matched=matched, rms_mm=f'{rms:.3f}', worst_mm=f'{worst_pad(fit, kp, jp):.2f}',
                         body_mm='' if bo is None else f'{bo:.2f}', status=status, note=note))
        print(f'{",".join(refs)[:24]:24s} {name[:36]:36s} rot +{th:3d}  offset ({tx:7.3f},{ty:7.3f})  '
              f'{method} n={matched} rms={rms:.3f} worst={rows[-1]["worst_mm"]} body={rows[-1]["body_mm"] or "-"} '
              f'{status} {note}', flush=True)

    with open(OUT, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['lcsc', 'footprint', 'refs', 'jlc_footprint', 'rotation', 'dx', 'dy',
                                          'method', 'matched', 'rms_mm', 'worst_mm', 'body_mm', 'status', 'note'])
        w.writeheader()
        w.writerows(rows)
    print(f'wrote {OUT}: {len(rows)} entries')


if __name__ == '__main__':
    main()
