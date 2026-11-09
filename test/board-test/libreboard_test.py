#!/usr/bin/env python3
"""LibreBoard rev3 board test. Runs on the board itself (CM5), as root.

  sudo python3 libreboard_test.py --board 3                      automatic checks, then guided checks
  sudo python3 libreboard_test.py --board 3 --auto               automatic checks only, no prompts
  sudo python3 libreboard_test.py --board 3 --camera /dev/video0 also take a photo at every visual check

Results are printed as the test runs and saved to /home/pi/libreboard-tests/<board>-<date>/
(report.md, report.json and any photos).

The test is non-destructive: nothing is written to the eMMC or the NVMe, eth0 is never reset (SSH may run
over it), and the services that own the OLED, the Sense HAT, the joystick and the displays are stopped only
for their own check and started again straight afterwards.

What it expects to find is set in BENCH below: the peripherals of the test bench.
"""
import argparse
import datetime
import glob
import json
import os
import re
import select
import shutil
import subprocess
import sys
import time

# run as root, but also see the packages installed for the pi user (luma.oled for the OLED lives there)
sys.path.extend(sorted(glob.glob('/home/*/.local/lib/python3*/site-packages')))

# --- test bench ------------------------------------------------------------------------------------------
BENCH = {
    'hdmi': True,           # monitor on J22
    'dsi': True,            # Raspberry Pi Touch Display 2 (5") on J5 CAM/DISP
    'nvme': True,           # SSD in J4
    'sense_hat': True,      # Sense HAT v2 on the 40-pin header J8
    'oled': 0x3D,           # SH1106 OLED on Qwiic J16 (i2c-1); None if not fitted
    'ina219': 0x40,         # INA219 module on Qwiic (i2c-1), nothing connected to it: reads ~0
    'bitaxe_j15': True,     # Bitaxe on J15 (USB-C to USB-A host adapter)
    'cm5_fan': True,        # fan on J14
}

# PMIC rails (vcgencmd pmic_read_adc): limits in volts. EXT5V is the board's 5 V from U14 (set to 5.19 V).
RAILS = {
    'EXT5V_V': (5.00, 5.40), 'HDMI_V': (5.00, 5.40), '3V3_SYS_V': (3.20, 3.40), '1V8_SYS_V': (1.75, 1.85),
    '1V1_SYS_V': (1.05, 1.15), 'DDR_VDD2_V': (1.05, 1.17), 'DDR_VDDQ_V': (0.57, 0.63), '0V8_SW_V': (0.76, 0.84),
    '0V8_AON_V': (0.76, 0.84), 'VDD_CORE_V': (0.70, 1.00), '3V3_DAC_V': (3.20, 3.40), '3V3_ADC_V': (3.20, 3.40),
    '3V7_WL_SW_V': (3.55, 3.90),
}

# USB controllers (sysfs path fragments) and what they feed on the board
USB_J11 = '1000480000.usb'                  # CM5 USB 2.0 (dwc2), J11 "USB2 (flash)"
USB_J15 = '1f00200000.usb'                  # RP1 xhci 0: J15 "USB3" through the HD3SS3220 mux
USB_HUB = '1f00300000.usb'                  # RP1 xhci 1: TUSB4041 hub U11
HUB_IDS = {('0451', '8142'), ('0451', '8140'), ('0451', '8044'), ('0451', '8040')}
HUB_PORTS = {1: 'J1', 2: 'J6', 3: 'J10', 4: 'J17'}   # TUSB4041 DN1..DN4 -> USB-C connectors (schematic)

I2C_ID = 0          # ID_SD/ID_SC: HAT EEPROM, EMC2305 U10, TCA9538 U17
I2C_HAT = 1         # GPIO2/3: Sense HAT, Qwiic J16
I2C_DSI = 10        # display: panel MCU 0x45, Goodix touch 0x5d
EMC2305 = 0x4D
TCA9538 = 0x70
SENSE_HAT_ADDRS = {0x1C: 'LSM9DS1 mag', 0x46: 'LED matrix MCU', 0x5C: 'LPS25H pressure', 0x5F: 'HTS221 humidity',
                   0x6A: 'LSM9DS1 accel/gyro'}

PASS, FAIL, WARN, SKIP, INFO = 'PASS', 'FAIL', 'WARN', 'SKIP', 'INFO'
COLOUR = {PASS: '\033[32m', FAIL: '\033[31m', WARN: '\033[33m', SKIP: '\033[90m', INFO: '\033[36m'}


# --- helpers ---------------------------------------------------------------------------------------------
class Report:
    def __init__(self, board, outdir):
        self.board, self.outdir, self.items = board, outdir, []

    def add(self, section, name, status, detail='', **data):
        self.items.append(dict(section=section, name=name, status=status, detail=detail, data=data))
        c = COLOUR[status] if sys.stdout.isatty() else ''
        e = '\033[0m' if c else ''
        print(f'  {c}{status:4s}{e}  {name}' + (f' - {detail}' if detail else ''), flush=True)

    def save(self, meta):
        os.makedirs(self.outdir, exist_ok=True)
        with open(os.path.join(self.outdir, 'report.json'), 'w') as f:
            json.dump(dict(meta=meta, results=self.items), f, indent=1)
        counts = {s: sum(1 for i in self.items if i['status'] == s) for s in (PASS, FAIL, WARN, SKIP, INFO)}
        lines = [f"# LibreBoard test: board {self.board}", '',
                 f"{meta['date']}, CM5 {meta['cm5_serial']}, script {meta['script']}", '',
                 ' · '.join(f'{k} {v}' for k, v in counts.items()), '',
                 '| Section | Check | Result | Detail |', '|---|---|---|---|']
        for i in self.items:
            lines.append(f"| {i['section']} | {i['name']} | {i['status']} | {i['detail'].replace('|', '/')} |")
        with open(os.path.join(self.outdir, 'report.md'), 'w') as f:
            f.write('\n'.join(lines) + '\n')
        return counts


def run(cmd, timeout=30, check=False):
    r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f'{cmd}: {r.stderr.strip()}')
    return r.stdout


def read(path, default=''):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def i2c_bus(n):
    try:
        import smbus2
        return smbus2.SMBus(n)
    except (ImportError, OSError):
        return None


def i2c_present(bus, addr):
    try:
        bus.read_byte(addr)
        return True
    except OSError:
        return False


def usb_devices():
    out = []
    for d in glob.glob('/sys/bus/usb/devices/*'):
        name = os.path.basename(d)
        if ':' in name or name.startswith('usb'):
            continue
        out.append(dict(path=name, vid=read(f'{d}/idVendor'), pid=read(f'{d}/idProduct'), speed=read(f'{d}/speed'),
                        product=read(f'{d}/product'), real=os.path.realpath(d)))
    return out


def ask(prompt, choices='yns'):
    """operator answer: y(es), n(o) or s(kip)"""
    while True:
        a = input(f'    {prompt} [{"/".join(choices)}] ').strip().lower()[:1]
        if a in choices:
            return a


def systemctl(action, units):
    for u in units:
        subprocess.run(['systemctl', action, u], capture_output=True, timeout=30)


def active(units):
    return [u for u in units if subprocess.run(['systemctl', 'is-active', '--quiet', u]).returncode == 0]


class Camera:
    def __init__(self, dev, outdir):
        self.dev, self.outdir, self.n = dev, outdir, 0

    def snap(self, name):
        if not self.dev:
            return None
        self.n += 1
        path = os.path.join(self.outdir, f'{self.n:02d}-{name}.jpg')
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'v4l2', '-i', self.dev, '-vf',
                        r'select=gte(n\,20)', '-frames:v', '1', path], capture_output=True, timeout=30)
        return path if os.path.exists(path) else None


# --- automatic checks ------------------------------------------------------------------------------------
def check_system(r):
    S = 'System'
    model = read('/proc/device-tree/model').rstrip('\x00')
    r.add(S, 'Module', PASS if 'Compute Module 5' in model else FAIL, model)
    emmc = os.path.exists('/dev/mmcblk0boot0')
    r.add(S, 'Boot storage', INFO, 'eMMC (CM5 with eMMC)' if emmc else 'no eMMC (CM5 Lite)')
    if emmc:
        r.add(S, 'SD slot J7', SKIP, 'CM5 with eMMC: J7 is only used by a CM5 Lite')
    else:
        sd = glob.glob('/sys/block/mmcblk*/device/type')
        r.add(S, 'SD slot J7', PASS if any(read(t) == 'SD' for t in sd) else WARN,
              'SD card found' if any(read(t) == 'SD' for t in sd) else 'no SD card in J7')
    temp = int(read('/sys/class/thermal/thermal_zone0/temp', '0')) / 1000
    r.add(S, 'CPU temperature', PASS if temp < 80 else WARN, f'{temp:.1f} °C')
    return emmc


def check_power(r):
    S = 'Power'
    adc = {}
    for line in run(['vcgencmd', 'pmic_read_adc']).splitlines():
        m = re.match(r'\s*(\S+)\s+(?:volt|current)\(\d+\)=([\d.]+)', line)
        if m:
            adc[m.group(1)] = float(m.group(2))
    for name, (lo, hi) in RAILS.items():
        v = adc.get(name)
        if v is None:
            r.add(S, name, WARN, 'not reported by the PMIC')
        else:
            r.add(S, name, PASS if lo <= v <= hi else FAIL, f'{v:.3f} V (limits {lo}-{hi} V)', volts=v)
    m = re.search(r'0x([0-9a-f]+)', run(['vcgencmd', 'get_throttled']))
    t = int(m.group(1), 16) if m else -1
    flags = {0: 'under-voltage now', 1: 'frequency capped now', 2: 'throttled now', 3: 'soft temp limit now',
             16: 'under-voltage since boot', 17: 'capped since boot', 18: 'throttled since boot',
             19: 'soft temp limit since boot'}
    bad = [d for b, d in flags.items() if t > 0 and t & (1 << b)]
    r.add(S, 'Throttling', PASS if t == 0 else FAIL if t & 0x10001 else WARN, ', '.join(bad) or 'none (0x0)')
    batt = adc.get('BATT_V', 0.0)
    r.add('RTC', 'Coin cell BT1', PASS if 2.5 <= batt <= 3.4 else WARN,
          f'BATT_V {batt:.2f} V' + ('' if batt >= 2.5 else ': no cell detected, fit a CR1220/CR1225 in BT1'))
    rtc = read('/sys/class/rtc/rtc0/date') + ' ' + read('/sys/class/rtc/rtc0/time')
    r.add('RTC', 'RTC readable', PASS if rtc.strip() else FAIL, rtc.strip() or 'no /dev/rtc0')


def check_ethernet(r):
    S = 'Ethernet'
    n = '/sys/class/net/eth0'
    if not os.path.exists(n):
        r.add(S, 'eth0', FAIL, 'no eth0 interface')
        return
    carrier = read(f'{n}/carrier', '0') == '1'
    speed, duplex = read(f'{n}/speed', '?'), read(f'{n}/duplex', '?')
    r.add(S, 'Link', PASS if carrier and speed == '1000' and duplex == 'full' else FAIL,
          f'{"up" if carrier else "down"}, {speed} Mb/s, {duplex} duplex (expect 1000 full)')
    if not carrier:
        return
    stat = lambda: {k: int(read(f'{n}/statistics/{k}', '0')) for k in
                    ('rx_errors', 'rx_crc_errors', 'rx_frame_errors', 'tx_errors', 'rx_dropped')}
    before = stat()
    gw = next((l.split()[2] for l in run(['ip', 'route', 'show', 'default', 'dev', 'eth0']).splitlines()
               if l.startswith('default')), None)
    if gw:
        out = run(['ping', '-I', 'eth0', '-c', '200', '-i', '0.01', '-s', '1472', '-q', gw], timeout=60)
        m = re.search(r'(\d+(?:\.\d+)?)% packet loss', out)
        loss = float(m.group(1)) if m else 100.0
        r.add(S, 'Ping gateway (200 x 1500 B)', PASS if loss == 0 else FAIL if loss > 2 else WARN,
              f'{gw}: {loss:g}% loss')
    else:
        r.add(S, 'Ping gateway', WARN, 'no default route on eth0')
    after = stat()
    grew = {k: after[k] - before[k] for k in after if after[k] > before[k] and k != 'rx_dropped'}
    r.add(S, 'Error counters', PASS if not grew else FAIL,
          'no new errors' if not grew else ', '.join(f'{k} +{v}' for k, v in grew.items()), totals=after)


def check_wireless(r):
    S = 'Wireless'
    w = read('/sys/class/net/wlan0/operstate')
    r.add(S, 'Wi-Fi (J3 nWireless_Dis open)', PASS if w else WARN, f'wlan0 {w}' if w else 'no wlan0')
    r.add(S, 'Bluetooth (J3 nBT_Dis open)', PASS if os.path.exists('/sys/class/bluetooth/hci0') else WARN,
          'hci0 present' if os.path.exists('/sys/class/bluetooth/hci0') else 'no hci0')


def find_hub():
    for d in usb_devices():
        if USB_HUB in d['real'] and (d['vid'], d['pid']) in HUB_IDS:
            return d
    return None


def check_usb(r):
    S = 'USB'
    hub = find_hub()
    if hub:
        ports = read(f"/sys/bus/usb/devices/{hub['path']}/maxchild")
        r.add(S, 'Hub U11 (TUSB4041)', PASS if hub['speed'] == '480' and ports == '4' else FAIL,
              f"{hub['vid']}:{hub['pid']} at {hub['path']}, {hub['speed']}M, {ports} ports")
        for p, j in HUB_PORTS.items():
            dev = next((d for d in usb_devices() if d['path'] == f"{hub['path']}.{p}"), None)
            r.add(S, f'Hub port {p} ({j})', INFO, f"{dev['product'] or dev['vid'] + ':' + dev['pid']} at {dev['speed']}M"
                  if dev else 'empty')
    else:
        r.add(S, 'Hub U11 (TUSB4041)', FAIL, 'hub not enumerated on the second RP1 USB controller')
    j15 = [d for d in usb_devices() if USB_J15 in d['real']]
    bitaxe = next((d for d in j15 if (d['vid'], d['pid']) == ('c0de', 'cafe')), None)
    if BENCH['bitaxe_j15']:
        r.add(S, 'J15 USB 2.0 data (Bitaxe)', PASS if bitaxe else FAIL,
              f"Bitaxe at {bitaxe['path']}, {bitaxe['speed']}M" if bitaxe else
              'no Bitaxe on J15' + (f" (found: {', '.join(d['product'] for d in j15)})" if j15 else ''))
    else:
        r.add(S, 'J15', INFO, ', '.join(f"{d['product']} {d['speed']}M" for d in j15) or 'nothing connected')
    j11 = [d for d in usb_devices() if USB_J11 in d['real']]
    r.add(S, 'J11 (CM5 USB 2.0)', INFO, ', '.join(f"{d['product']} {d['speed']}M" for d in j11) or
          'nothing connected (J11 has no VBUS: test with a self-powered device)')


def check_ttys(r):
    S = 'Bitaxe'
    if not BENCH['bitaxe_j15']:
        return
    ttys = glob.glob('/dev/serial/by-id/*Bitaxe*')
    r.add(S, 'Serial ports', PASS if ttys else FAIL, ', '.join(os.path.basename(os.path.realpath(t)) for t in ttys)
          or 'none')
    try:
        import urllib.request
        with urllib.request.urlopen('http://127.0.0.1:7785/api/v0/miner', timeout=5) as u:
            d = json.load(u)
        r.add(S, 'Miner (mujina)', INFO, f"{d.get('hashrate', 0) / 1e12:.2f} TH/s, {d.get('shares_submitted', 0)} shares"
              ' (not a board check)')
    except Exception as e:
        r.add(S, 'Miner (mujina)', INFO, f'API not reachable ({e.__class__.__name__})')


def check_pcie(r):
    S = 'M.2 / PCIe'
    nv = sorted(glob.glob('/sys/class/nvme/nvme*'))
    if not nv:
        r.add(S, 'NVMe', FAIL if BENCH['nvme'] else SKIP, 'no NVMe device')
        return
    pci = os.path.realpath(f'{nv[0]}/device')
    speed, width = read(f'{pci}/current_link_speed'), read(f'{pci}/current_link_width')
    r.add(S, 'NVMe', PASS, f"{read(nv[0] + '/model')} ({read(nv[0] + '/firmware_rev')})")
    r.add(S, 'PCIe link', PASS if speed.startswith(('5.0', '8.0')) and width == '1' else FAIL,
          f'{speed} x{width} (CM5 default Gen2 x1)')
    dev = '/dev/' + os.path.basename(nv[0]) + 'n1'
    t0 = time.perf_counter()
    res = subprocess.run(['dd', f'if={dev}', 'of=/dev/null', 'bs=4M', 'count=128', 'iflag=direct', 'status=none'],
                         capture_output=True, timeout=120)
    dt = time.perf_counter() - t0
    mbs = 512 / dt if res.returncode == 0 else 0
    r.add(S, 'Read 512 MiB (direct)', PASS if mbs >= 300 else FAIL, f'{mbs:.0f} MB/s (expect >= 300 on Gen2 x1)')
    temps = glob.glob(f'{nv[0]}/hwmon*/temp1_input') or glob.glob(f'{pci}/nvme/*/hwmon*/temp1_input')
    for t in temps[:1]:
        r.add(S, 'NVMe temperature', INFO, f'{int(read(t, "0")) / 1000:.0f} °C')


def check_i2c(r):
    S = 'I2C'
    b0, b1, b10 = i2c_bus(I2C_ID), i2c_bus(I2C_HAT), i2c_bus(I2C_DSI)
    if not b0:
        r.add(S, f'i2c-{I2C_ID}', FAIL, 'bus missing (dtparam=i2c0=on?) or smbus2 not installed')
        return None
    try:
        pid, mfr = b0.read_byte_data(EMC2305, 0xFD), b0.read_byte_data(EMC2305, 0xFE)
        r.add(S, 'U10 EMC2305 fan controller', PASS if (pid, mfr) == (0x34, 0x5D) else FAIL,
              f'i2c-{I2C_ID} 0x{EMC2305:02X}: product 0x{pid:02X}, maker 0x{mfr:02X}')
    except OSError:
        r.add(S, 'U10 EMC2305 fan controller', FAIL, f'no answer at i2c-{I2C_ID} 0x{EMC2305:02X}')
    tca = None
    try:
        regs = [b0.read_byte_data(TCA9538, k) for k in range(4)]
        tca = b0
        r.add(S, 'U17 TCA9538 expander', PASS, f'i2c-{I2C_ID} 0x70: in 0x{regs[0]:02X} out 0x{regs[1]:02X} '
              f'config 0x{regs[3]:02X}')
    except OSError:
        r.add(S, 'U17 TCA9538 expander', FAIL, 'no answer at 0x70: U17 is hand-fitted, is it soldered? '
              '(needed for the status LED and the hub software reset)')
    r.add(S, 'HAT ID EEPROM', INFO, 'present (0x50)' if i2c_present(b0, 0x50) else 'none (only HATs with an EEPROM)')
    if b1:
        if BENCH['sense_hat']:
            miss = [f'{v} 0x{a:02X}' for a, v in SENSE_HAT_ADDRS.items()
                    if not (i2c_present(b1, a) or os.path.exists(f'/sys/bus/i2c/devices/{I2C_HAT}-{a:04x}'))]
            r.add(S, 'Sense HAT (J8 I2C)', PASS if not miss else FAIL, 'all 5 chips answer' if not miss
                  else 'missing: ' + ', '.join(miss))
        if BENCH['oled'] is not None:
            ok = i2c_present(b1, BENCH['oled'])
            r.add(S, 'OLED (Qwiic J16)', PASS if ok else FAIL, f"0x{BENCH['oled']:02X} {'answers' if ok else 'missing'}")
        if BENCH['ina219'] is not None:
            a = BENCH['ina219']
            try:
                sw = lambda v: ((v & 0xFF) << 8) | (v >> 8)
                shunt = sw(b1.read_word_data(a, 0x01))
                shunt = (shunt - 0x10000 if shunt & 0x8000 else shunt) * 0.01      # mV
                bus_v = (sw(b1.read_word_data(a, 0x02)) >> 3) * 0.004
                r.add(S, 'INA219 (Qwiic)', PASS if abs(shunt) < 1.0 else WARN,
                      f'shunt {shunt:.2f} mV, bus {bus_v:.2f} V (nothing connected: shunt ~0, bus floats)')
            except OSError:
                r.add(S, 'INA219 (Qwiic)', FAIL, f'no answer at 0x{a:02X}')
    if BENCH['dsi']:
        found = {a: os.path.exists(f'/sys/bus/i2c/devices/{I2C_DSI}-{a:04x}') or (b10 and i2c_present(b10, a))
                 for a in (0x45, 0x5D)}
        r.add(S, 'DSI display I2C (J5)', PASS if all(found.values()) else FAIL,
              f"panel MCU 0x45 {'ok' if found[0x45] else 'missing'}, touch 0x5D {'ok' if found[0x5D] else 'missing'}")
    return tca


def check_displays(r):
    S = 'Displays'
    cons = {os.path.basename(c).split('-', 1)[1]: c for c in glob.glob('/sys/class/drm/card*-*')}
    hdmi = cons.get('HDMI-A-1')
    if BENCH['hdmi']:
        st = read(f'{hdmi}/status') if hdmi else 'missing'
        name = ''
        try:
            with open(f'{hdmi}/edid', 'rb') as f:
                e = f.read()
            ok = e[:8] == bytes([0, 255, 255, 255, 255, 255, 255, 0])
            for i in (54, 72, 90, 108):
                if e[i:i + 4] == bytes([0, 0, 0, 0xFC]):
                    name = e[i + 5:i + 18].decode('ascii', 'replace').strip()
        except (OSError, TypeError):
            ok = False
        r.add(S, 'HDMI J22', PASS if st == 'connected' and ok else FAIL,
              f"{st}, EDID {'valid' if ok else 'missing'}" + (f', {name}' if name else '') +
              (f", {read(hdmi + '/modes').splitlines()[0]}" if ok and read(hdmi + '/modes') else ''))
    if BENCH['dsi']:
        dsi = next((c for k, c in cons.items() if k.startswith('DSI')), None)
        st = read(f'{dsi}/status') if dsi else 'missing'
        r.add(S, 'DSI J5', PASS if st == 'connected' else FAIL, st)


def input_devices():
    devs, name = {}, None
    for line in read('/proc/bus/input/devices').splitlines():
        if line.startswith('N: Name='):
            name = line[9:-1]
        elif line.startswith('H: Handlers=') and name:
            ev = re.search(r'(event\d+)', line)
            if ev:
                devs[name] = '/dev/input/' + ev.group(1)
    return devs


def check_inputs(r):
    S = 'Inputs'
    devs = input_devices()
    r.add(S, 'Power button SW1 (pwr_button)', PASS if 'pwr_button' in devs else FAIL, devs.get('pwr_button', 'missing'))
    if BENCH['dsi']:
        t = next((n for n in devs if 'Touch' in n or 'Goodix' in n), None)
        r.add(S, 'Touch controller', PASS if t else FAIL, t or 'missing')
    if BENCH['sense_hat']:
        j = next((n for n in devs if n == 'Raspberry Pi Sense HAT Joystick'), None)
        r.add(S, 'Sense HAT joystick', PASS if j else FAIL, j or 'missing')


def emc_rpm(bus, ch):
    base = 0x30 + 0x10 * ch
    count = ((bus.read_byte_data(EMC2305, base + 0x0E) << 8) | bus.read_byte_data(EMC2305, base + 0x0F)) >> 3
    return None if count >= 0x1FF0 or count == 0 else 3932160 * 2 // count


def check_fans(r, fan_test):
    S = 'Fans'
    for h in glob.glob('/sys/class/hwmon/hwmon*'):
        if read(f'{h}/name') == 'pwmfan':
            rpm = int(read(f'{h}/fan1_input', '0'))
            r.add(S, 'CM5 fan J14', PASS if rpm > 300 else (FAIL if BENCH['cm5_fan'] else INFO), f'{rpm} RPM')
    b0 = i2c_bus(I2C_ID)
    if not b0:
        return
    try:
        rpms = {ch: emc_rpm(b0, ch) for ch in range(4)}
    except OSError:
        r.add(S, 'J51-J54 (EMC2305)', FAIL, 'EMC2305 not readable')
        return
    with_fan = [ch for ch, v in rpms.items() if v]
    for ch, v in rpms.items():
        r.add(S, f'J5{ch + 1} 12 V fan {ch + 1}', PASS if v else (WARN if fan_test else INFO),
              f'{v} RPM' if v else 'no fan / no tach (connect a 12 V 4-pin fan to test U4 12 V and this channel)')
    if fan_test and with_fan:
        saved = {ch: b0.read_byte_data(EMC2305, 0x30 + 0x10 * ch) for ch in with_fan}
        try:
            for ch in with_fan:
                b0.write_byte_data(EMC2305, 0x30 + 0x10 * ch, 0x50)
            time.sleep(5)
            low = {ch: emc_rpm(b0, ch) or 0 for ch in with_fan}
            for ch in with_fan:
                b0.write_byte_data(EMC2305, 0x30 + 0x10 * ch, 0xFF)
            time.sleep(5)
            high = {ch: emc_rpm(b0, ch) or 0 for ch in with_fan}
        finally:
            for ch, v in saved.items():
                b0.write_byte_data(EMC2305, 0x30 + 0x10 * ch, v)
        for ch in with_fan:
            r.add(S, f'J5{ch + 1} PWM control', PASS if high[ch] > low[ch] * 1.2 else FAIL,
                  f'31% drive {low[ch]} RPM -> 100% drive {high[ch]} RPM')


def check_sense_hat(r):
    S = 'Sense HAT'
    if not BENCH['sense_hat']:
        return
    try:
        from sense_hat import SenseHat
        s = SenseHat()
        h, p = s.get_humidity(), 0.0
        for _ in range(20):                 # the LPS25H returns 0 until its first conversion is done
            p = s.get_pressure()
            if p > 0:
                break
            time.sleep(0.1)
        a = s.get_accelerometer_raw()
        g = (a['x'] ** 2 + a['y'] ** 2 + a['z'] ** 2) ** 0.5
        ok = 0 < h <= 100 and 800 < p < 1100 and 0.8 < g < 1.2
        r.add(S, 'Sensors', PASS if ok else FAIL, f'humidity {h:.0f} %, pressure {p:.0f} hPa, gravity {g:.2f} g')
    except Exception as e:
        r.add(S, 'Sensors', FAIL, f'{e.__class__.__name__}: {e}')


def check_hub_reset(r, tca):
    """pulse HUB_SW_RESETz (U17 P7 -> U19 MR) and check that the hub drops off and comes back"""
    S = 'USB'
    hub = find_hub()
    if not (tca and hub):
        r.add(S, 'Hub software reset (U17 P7)', SKIP, 'needs U17 and an enumerated hub')
        return
    num = read(f"/sys/bus/usb/devices/{hub['path']}/devnum")
    out, cfg = tca.read_byte_data(TCA9538, 0x01), tca.read_byte_data(TCA9538, 0x03)
    try:
        tca.write_byte_data(TCA9538, 0x01, out & 0x7F)
        tca.write_byte_data(TCA9538, 0x03, cfg & 0x7F)
        time.sleep(0.005)
    finally:
        tca.write_byte_data(TCA9538, 0x03, cfg | 0x80)
        tca.write_byte_data(TCA9538, 0x01, out)
    t0 = time.time()
    back = None
    while time.time() - t0 < 10:
        time.sleep(0.3)
        h = find_hub()
        if h and read(f"/sys/bus/usb/devices/{h['path']}/devnum") != num:
            back = time.time() - t0
            break
    r.add(S, 'Hub software reset (U17 P7)', PASS if back else FAIL,
          f're-enumerated after {back:.1f} s' if back else 'hub did not reset (same device number after 10 s)')


def check_dmesg(r):
    S = 'Kernel log'
    bad = re.compile(r'under-voltage|over-?current|PCIe Bus Error|AER: (Corrected|Uncorrected|Multiple)|'
                     r'nvme.*(timeout|reset|I/O error)|'
                     r'mmc\d.*(error|timeout)|usb \S+: (device descriptor read|device not accepting|'
                     r'unable to enumerate)|error -71|EXT4-fs error|I/O error', re.I)
    hits = [l for l in run(['dmesg']).splitlines() if bad.search(l)]
    r.add(S, 'Hardware errors since boot', PASS if not hits else FAIL,
          'none' if not hits else f'{len(hits)} lines, first: {hits[0][:120]}', lines=hits[:30])


# --- guided checks ---------------------------------------------------------------------------------------
def wait_for(pred, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(0.3)
    return None


def guided_hub_ports(r):
    S = 'USB ports'
    hub = find_hub()
    if not hub:
        r.add(S, 'Hub ports', SKIP, 'hub not enumerated')
        return
    print('\n  Hub ports: use one USB device with a USB-C plug (e.g. a USB-C flash drive), each port both ways up.')
    for p, j in HUB_PORTS.items():
        at = lambda: next((d for d in usb_devices() if d['path'] == f"{hub['path']}.{p}"), None)
        results = []
        for side in ('one way up', 'turned over'):
            if input(f'    {j}: plug the device in {side}, then press Enter (s = skip) ').strip().lower() == 's':
                results.append(None)
                break
            d = wait_for(at, 10)
            results.append(d)
            if d:
                print(f"      seen: {d['product'] or d['vid'] + ':' + d['pid']} at {d['speed']}M")
                input(f'    unplug it from {j}, then press Enter ')
                wait_for(lambda: not at(), 10)
            else:
                elsewhere = [x for x in usb_devices() if x['path'].startswith(hub['path'] + '.')]
                print('      nothing on this port' + (f" (seen on {elsewhere[0]['path']})" if elsewhere else ''))
        if results and results[0] is None:
            r.add(S, f'{j} (hub port {p})', SKIP, 'skipped')
        else:
            ok = len(results) == 2 and all(results)
            r.add(S, f'{j} (hub port {p})', PASS if ok else FAIL,
                  ', '.join(f"{s}: {d['speed'] + 'M' if d else 'nothing'}" for s, d in zip(('side A', 'side B'), results)))


def guided_j15(r):
    S = 'USB ports'
    a = input('\n    J15: unplug the Bitaxe adapter, plug a USB 3 device (USB-C flash drive) in one way up, '
              'press Enter (s = skip) ').strip().lower()
    if a == 's':
        r.add(S, 'J15 SuperSpeed', SKIP, 'skipped')
        return
    res = []
    for side in ('side A', 'side B'):
        if side == 'side B':
            input('    unplug it, turn it over, plug it back into J15, press Enter ')
        d = wait_for(lambda: next((x for x in usb_devices() if USB_J15 in x['real']
                                   and x['vid'] != 'c0de'), None), 10)
        res.append(d)
        print(f"      seen: {d['product']} at {d['speed']}M" if d else '      nothing seen')
    ok = all(d and d['speed'] == '5000' for d in res)
    r.add(S, 'J15 SuperSpeed both ways up (HD3SS3220)', PASS if ok else FAIL,
          ', '.join(f"{s}: {d['speed'] + 'M' if d else 'nothing'}" for s, d in zip(('side A', 'side B'), res)))
    input('    plug the Bitaxe back into J15, press Enter ')


def guided_j11(r):
    S = 'USB ports'
    a = input('\n    J11: plug a SELF-POWERED USB device into J11 (it gets no VBUS from the board, e.g. the powered '
              'Bitaxe), press Enter (s = skip) ').strip().lower()
    if a == 's':
        r.add(S, 'J11 (CM5 USB 2.0)', SKIP, 'skipped')
        return
    d = wait_for(lambda: next((x for x in usb_devices() if USB_J11 in x['real']), None), 10)
    r.add(S, 'J11 (CM5 USB 2.0)', PASS if d else FAIL, f"{d['product']} at {d['speed']}M" if d else 'nothing seen')


def wait_event(dev_path, keys, timeout):
    """True once an event of type/code in keys arrives on the evdev node"""
    import evdev
    dev = evdev.InputDevice(dev_path)
    t0 = time.time()
    while time.time() - t0 < timeout:
        rl, _, _ = select.select([dev.fd], [], [], 0.5)
        if rl:
            for ev in dev.read():
                if (ev.type, ev.code) in keys or ('any', ev.type) in keys:
                    return True
    return False


def guided_inputs(r):
    S = 'Inputs'
    devs = input_devices()
    if BENCH['dsi']:
        t = next((v for n, v in devs.items() if 'Touch' in n or 'Goodix' in n), None)
        if t:
            print('\n    Touch the DSI screen (15 s)...')
            ok = wait_event(t, {('any', 3)}, 15)
            r.add(S, 'Touch', PASS if ok else FAIL, 'touch events seen' if ok else 'no touch seen')
    if BENCH['sense_hat'] and 'Raspberry Pi Sense HAT Joystick' in devs:
        owners = active(['joystick-remap', 'doom-launcher'])
        systemctl('stop', owners)
        try:
            print('    Press the Sense HAT joystick in the middle (15 s)...')
            ok = wait_event(devs['Raspberry Pi Sense HAT Joystick'], {('any', 1)}, 15)
        finally:
            systemctl('start', owners)
        r.add(S, 'Sense HAT joystick', PASS if ok else FAIL, 'press seen' if ok else 'no press seen')
    if 'pwr_button' in devs:
        inh = subprocess.Popen(['systemd-inhibit', '--what=handle-power-key', '--who=libreboard-test',
                                '--why=power button test', '--mode=block', 'sleep', '30'])
        time.sleep(0.5)
        try:
            print('    Press SW1 (power button) SHORTLY, under a second (15 s)...')
            ok = wait_event(devs['pwr_button'], {(1, 116)}, 15)
        finally:
            inh.terminate()
        r.add(S, 'Power button SW1', PASS if ok else FAIL, 'KEY_POWER seen' if ok else 'no press seen')


def visual(r, cam, section, name, show, question, cleanup=None):
    """run show(), take a photo, ask the operator, clean up"""
    try:
        show()
        time.sleep(1.5)
        photo = cam.snap(re.sub(r'\W+', '-', name.lower()))
        a = ask(question)
    except Exception as e:
        r.add(section, name, FAIL, f'{e.__class__.__name__}: {e}')
        return
    finally:
        if cleanup:
            cleanup()
    r.add(section, name, PASS if a == 'y' else FAIL if a == 'n' else SKIP, 'operator: ' + {'y': 'yes', 'n': 'no',
          's': 'skipped'}[a], photo=photo)


def guided_visual(r, cam, tca):
    print('\n  Visual checks' + (f' (photos from {cam.dev})' if cam.dev else ''))
    # displays: colour bars on HDMI and DSI, desktop stopped meanwhile
    if BENCH['hdmi'] or BENCH['dsi']:
        dm = active(['lightdm'])
        procs = []

        def show():
            systemctl('stop', dm)
            time.sleep(2)
            for card in sorted(glob.glob('/dev/dri/card*')):
                procs.append(subprocess.Popen(['kmstest', f'--device={card}', '-T', 'smpte'], stdin=subprocess.PIPE,
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

        def cleanup():
            for p in procs:
                p.kill()
            systemctl('start', dm)
        visual(r, cam, 'Displays', 'HDMI and DSI colour bars', show,
               'Do the HDMI monitor AND the touch display both show colour bars?', cleanup)
    # OLED
    if BENCH['oled'] is not None:
        owners = active(['sensor-display'])

        def show_oled():
            systemctl('stop', owners)
            from luma.core.interface.serial import i2c
            from luma.oled.device import sh1106
            from luma.core.render import canvas
            dev = sh1106(i2c(port=I2C_HAT, address=BENCH['oled']), rotate=0)
            with canvas(dev) as c:
                c.rectangle(dev.bounding_box, outline='white')
                c.text((10, 10), 'LIBREBOARD', fill='white')
                c.text((10, 30), 'OLED TEST', fill='white')
                for x in range(0, 128, 8):
                    c.rectangle((x, 54, x + 3, 60), fill='white')
        visual(r, cam, 'Qwiic', 'OLED', show_oled, 'Does the OLED show a frame, "LIBREBOARD / OLED TEST" and a bar?',
               lambda: systemctl('start', owners))
    # Sense HAT LED matrix
    if BENCH['sense_hat']:
        owners = active(['led-animation', 'doom-launcher'])

        def show_matrix():
            systemctl('stop', owners)
            from sense_hat import SenseHat
            s = SenseHat()
            s.low_light = True
            for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)):
                s.clear(c)
                time.sleep(0.6)
        visual(r, cam, 'Sense HAT', 'LED matrix', show_matrix,
               'Did the Sense HAT matrix show red, green, blue, then stay white?', lambda: systemctl('start', owners))
    # CM5 activity LED
    act = '/sys/class/leds/ACT'
    if os.path.exists(act):
        trig = re.search(r'\[(\S+)\]', read(f'{act}/trigger'))
        trig = trig.group(1) if trig else 'mmc0'

        def blink():
            with open(f'{act}/trigger', 'w') as f:
                f.write('timer')

        def restore():
            with open(f'{act}/trigger', 'w') as f:
                f.write(trig)
        visual(r, cam, 'LEDs', 'ACT LED', blink, 'Is the green "Act" LED blinking steadily?', restore)
    # status LED U9 (SK6812 via SPI0 + U16, gated by U17 P0)
    if tca:
        visual(r, cam, 'LEDs', 'Status LED U9', lambda: status_led_cycle(tca),
               'Did the "Status" LED show red, green, blue, then white?', lambda: status_led(tca, 0, 0, 0))
    else:
        r.add('LEDs', 'Status LED U9', SKIP, 'needs U17 (its P0 opens the U16 buffer)')
    # Ethernet LEDs during traffic
    gw = next((l.split()[2] for l in run(['ip', 'route', 'show', 'default', 'dev', 'eth0']).splitlines()
               if l.startswith('default')), None)
    if gw:
        traffic = []
        visual(r, cam, 'LEDs', 'Ethernet MagJack LEDs',
               lambda: traffic.append(subprocess.Popen(['ping', '-I', 'eth0', '-i', '0.01', '-c', '1500', gw],
                                                       stdout=subprocess.DEVNULL)),
               'Are both MagJack LEDs working (link on, activity flickering)?', lambda: [p.kill() for p in traffic])
    # M.2 activity LED while reading the SSD
    if BENCH['nvme'] and glob.glob('/dev/nvme0n1'):
        rd = []
        visual(r, cam, 'LEDs', 'M.2 activity LED',
               lambda: rd.append(subprocess.Popen(['dd', 'if=/dev/nvme0n1', 'of=/dev/null', 'bs=1M', 'count=4000',
                                                  'iflag=direct'], stderr=subprocess.DEVNULL)),
               'Is the "M2 Act LED" lit/flickering while the SSD is read?', lambda: [p.kill() for p in rd])


def status_led(tca, r_, g, b, w=0):
    import spidev
    spi = spidev.SpiDev()
    spi.open(0, 0)
    spi.max_speed_hz, spi.mode = 6_400_000, 0
    try:
        spi.no_cs = True
    except OSError:
        pass
    enc = lambda v: [0xF0 if (v >> i) & 1 else 0xC0 for i in range(7, -1, -1)]
    data = [0] * 60 + enc(g) + enc(r_) + enc(b) + enc(w) + [0] * 60
    out, cfg = tca.read_byte_data(TCA9538, 0x01), tca.read_byte_data(TCA9538, 0x03)
    tca.write_byte_data(TCA9538, 0x01, out | 0x01)          # P0 high first: gate shut
    tca.write_byte_data(TCA9538, 0x03, cfg & 0xFE)          # P0 output
    try:
        tca.write_byte_data(TCA9538, 0x01, out & 0xFE)      # open the gate
        spi.xfer2(data)
    finally:
        tca.write_byte_data(TCA9538, 0x01, out | 0x01)
        spi.close()


def status_led_cycle(tca):
    for c in ((60, 0, 0), (0, 60, 0), (0, 0, 60), (0, 0, 0, 60)):
        status_led(tca, *c)
        time.sleep(0.8)


def guided_measure(r):
    S = 'Power'
    v = input('\n    Measure +12V at TP2 (12V test point) with a multimeter, enter volts (Enter = skip): ').strip()
    try:
        x = float(v.replace(',', '.'))
        r.add(S, '+12V (U4) at TP2', PASS if 11.5 <= x <= 12.7 else FAIL, f'{x:.2f} V (expect 12.1 V)')
    except ValueError:
        r.add(S, '+12V (U4) at TP2', SKIP, 'not measured')


# --- main ------------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--board', help='board number / label (asked for if missing)')
    ap.add_argument('--auto', action='store_true', help='automatic checks only, no operator prompts')
    ap.add_argument('--camera', help='V4L2 webcam (e.g. /dev/video0) for photos of the visual checks')
    ap.add_argument('--fan-test', action='store_true', help='drive connected 12 V fans at 31 %% and 100 %%')
    ap.add_argument('--out', default='/home/pi/libreboard-tests', help='report directory')
    args = ap.parse_args()
    if os.geteuid():
        sys.exit('run as root: sudo python3 libreboard_test.py ...')
    board = args.board or ('unknown' if args.auto else input('Board number / label: ').strip() or 'unknown')
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    outdir = os.path.join(args.out, f'{board}-{stamp}')
    os.makedirs(outdir, exist_ok=True)
    r = Report(board, outdir)
    serial = re.search(r'Serial\s*:\s*(\S+)', read('/proc/cpuinfo'))
    meta = dict(board=board, date=stamp, cm5_serial=serial.group(1) if serial else '?', script='rev3-1',
                kernel=os.uname().release)
    print(f'LibreBoard rev3 test, board {board}, CM5 {meta["cm5_serial"]}\n')
    tca = None

    for title, fn in (('System', check_system), ('Power', check_power), ('Ethernet', check_ethernet),
                      ('Wireless', check_wireless), ('USB', check_usb), ('Bitaxe', check_ttys),
                      ('M.2 / PCIe', check_pcie), ('I2C', check_i2c), ('Displays', check_displays),
                      ('Inputs', check_inputs), ('Sense HAT', check_sense_hat), ('Kernel log', check_dmesg)):
        print(f'[{title}]')
        try:
            res = fn(r)
        except Exception as e:
            r.add(title, 'check crashed', FAIL, f'{e.__class__.__name__}: {e}')
            res = None
        if fn is check_i2c:
            tca = res
    print('[Fans]')
    check_fans(r, args.fan_test)
    print('[USB hub reset]')
    check_hub_reset(r, tca)

    if not args.auto:
        print('\n=== Guided checks (Enter to continue, s to skip) ===')
        cam = Camera(args.camera, outdir)
        for fn in (guided_hub_ports, guided_j15, guided_j11, guided_inputs):
            try:
                fn(r)
            except Exception as e:
                r.add('Guided', fn.__name__, FAIL, f'{e.__class__.__name__}: {e}')
        guided_visual(r, cam, tca)
        guided_measure(r)

    counts = r.save(meta)
    print(f"\nResult: {counts[PASS]} pass, {counts[FAIL]} fail, {counts[WARN]} warn, {counts[SKIP]} skipped")
    for i in r.items:
        if i['status'] in (FAIL, WARN):
            print(f"  {i['status']}  {i['section']} / {i['name']}: {i['detail']}")
    print(f'Report: {outdir}/report.md')
    sys.exit(1 if counts[FAIL] else 0)


if __name__ == '__main__':
    main()
