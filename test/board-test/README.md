# LibreBoard rev3 board test

`libreboard_test.py` tests an assembled LibreBoard rev3 from the CM5 on the board. It runs the automatic
checks first, then walks the operator through the checks that need hands or eyes, and saves a report per
board.

```bash
scp test/board-test/libreboard_test.py pi@<board-ip>:/home/pi/
ssh pi@<board-ip>
sudo python3 libreboard_test.py --board 2                  # full test: automatic + guided
sudo python3 libreboard_test.py --board 2 --auto           # automatic checks only (no prompts)
sudo python3 libreboard_test.py --board 2 --camera /dev/video0   # photo at every visual check
sudo python3 libreboard_test.py --board 2 --fan-test       # also drive connected 12 V fans
```

The report goes to `/home/pi/libreboard-tests/<board>-<date>/` (`report.md`, `report.json`, photos). The
exit code is 1 if anything failed.

The test does not write to the eMMC or the SSD and never resets `eth0`, so it can run over SSH on Ethernet.
Services that own a device (OLED, Sense HAT, joystick, desktop) are stopped only during their own check.

## Test bench

As set in `BENCH` at the top of the script; change it if the bench differs.

| Where | What is connected |
|---|---|
| J22 | HDMI monitor |
| J5 CAM/DISP | Raspberry Pi Touch Display 2 (5"), overlay `vc4-kms-dsi-ili9881-5inch,dsi0` |
| J4 | NVMe SSD |
| J8 | Sense HAT v2 (overlay `rpi-sense-v2`) |
| J16 Qwiic | SH1106 OLED (0x3D) and INA219 module (0x40, nothing on its input) |
| J15 | Bitaxe (USB-C to USB-A host adapter) |
| J14 | CM5 fan |
| J100/J101 | 12-24 V supply |
| Ethernet | network with a gateway |

For the guided checks also have ready: a USB-C flash drive (USB 3), a self-powered USB device for J11, and
a multimeter for TP2 (+12V).

## What is checked

**Automatic**
- CM5 and boot storage; SD slot J7 (only with a CM5 Lite).
- PMIC rails: EXT5V (U14, 5.19 V), HDMI 5 V and all CM5 rails, throttling/under-voltage flags.
- RTC and coin cell BT1 (BATT_V).
- Ethernet: 1000 Mb/s full duplex, 200 × 1500-byte pings to the gateway, no new error counts.
- Wi-Fi and Bluetooth (J3 jumpers open).
- USB: TUSB4041 hub U11 on the second RP1 controller with 4 ports; Bitaxe on J15; J11 bus.
- M.2: NVMe found, PCIe 5 GT/s ×1, 512 MiB direct read at ≥ 300 MB/s.
- I2C: EMC2305 U10 (ID 0x34/0x5D), TCA9538 U17 at 0x70, Sense HAT (5 chips), OLED, INA219 (shunt ≈ 0),
  DSI panel MCU and touch controller.
- HDMI connected with a valid EDID; DSI connected; power button, touch and joystick input devices.
- Sense HAT sensors (humidity, pressure, gravity ≈ 1 g); CM5 fan RPM; 12 V fan tach on J51–J54.
- Hub software reset: pulses U17 P7 (HUB_SW_RESETz) and checks that the hub re-enumerates.
- Kernel log: under-voltage, over-current, PCIe AER, NVMe, eMMC and USB enumeration errors.

**Guided** (operator; `s` skips a step)
- J1, J6, J10, J17 (hub ports 1–4) and J15 SuperSpeed: plug the USB-C drive in **both ways up**. J15 must
  reach 5000M both ways (HD3SS3220 orientation mux).
- J11: a self-powered device. J11 has no VBUS from the board.
- Touch screen, Sense HAT joystick, power button SW1 (short press; shutdown is inhibited meanwhile).
- Visual: colour bars on HDMI and DSI (the desktop is stopped for this), OLED pattern, Sense HAT matrix,
  ACT LED blink, status LED U9, MagJack LEDs under traffic, M.2 activity LED while reading the SSD.
- +12V (U4) at TP2 with a multimeter: 11.5–12.7 V.

With `--camera`, each visual check also saves a photo to the report folder, so the result can be reviewed
afterwards. A UVC webcam on one of the hub ports also exercises that port.

## Needs on the board

- **U17 (TCA9538DBR)** is fitted by hand after JLC assembly. Without it the status LED U9 cannot be driven
  (R52 keeps the U16 buffer shut) and the hub software reset cannot be tested.
- **BT1** needs a CR1220/CR1225 cell for the RTC check to pass; without one it is a warning.
- The 12 V fan channels (and U4's 12 V) are only tested with a 4-pin fan on J51–J54 (`--fan-test`), or by
  measuring TP2.

## Board 1 (CM5 ef3f03a6…), 2026-11-09, automatic checks

41 pass, 1 fail, 1 warning: U17 not fitted yet (fail); no coin cell in BT1 (warning). Ethernet at
1000 Mb/s with 0 % loss, hub U11 enumerates, NVMe at 420 MB/s, EXT5V 5.197 V, no kernel errors.
