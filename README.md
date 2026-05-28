# atbm-cli — ATBM6441 Firmware Burn Tool

Cross-platform CLI tool for flashing firmware to AltoBeam ATBM6441 WiFi IoT chips via UART. Replaces the Windows-only Altobem WIFI IOT GUI with a simple, scriptable command-line interface.

## Overview

| Feature | Description |
|---|---|
| **Platform** | Linux, macOS, Windows (any OS with serial port access) |
| **Transport** | UART over USB-serial (FT232, CP2102, etc.) |
| **Baud rates** | 115200, 1000000, 1500000 |
| **Dependencies** | `pyserial`, `tqdm` — zero proprietary DLLs |
| **Protocol** | AT commands (`AT+START`, `AT+SEND`, `AT+REBOOT`) |

## Installation

```bash
pip install -e .
# or with dev deps
pip install -e ".[dev]"
```

## Quick Start

```bash
# Query chip info
atbm6441-cli info --port /dev/ttyUSB0 gmr

# Burn firmware
atbm6441-cli burn --port /dev/ttyUSB0 --baud 1000000 \
  --firmware fw_update1.bin \
  --flashcode fw_update2.bin \
  --bootloader bootloader_step1.bin

# Burn KEY data
atbm6441-cli key --port /dev/ttyUSB0 --keyfile keys.csv

# Read/write memory
atbm6441-cli mem r 0x16a00020 --port /dev/ttyUSB0
atbm6441-cli mem w 0x100000 0xDEADBEEF --port /dev/ttyUSB0

# Read flash content
atbm6441-cli read --port /dev/ttyUSB0 --addr 0x000000 --len 0x100000 output.bin

# Verify burned firmware
atbm6441-cli verify --port /dev/ttyUSB0 --firmware fw_update1.bin
```

## Commands

### `burn` — Flash firmware images

Burns bootloader, CODE1 (ICCM), CODE2 (Flash), and KEY data in sequence.

```bash
atbm6441-cli burn \
  --port /dev/ttyUSB0 \
  --baud 1000000 \
  --firmware fw_update1.bin \
  --flashcode fw_update2.bin \
  --bootloader bootloader_step1.bin \
  --keyfile keys.csv \
  --mac aa:bb:cc:dd:ee:ff
```

| Flag | Description | Default |
|---|---|---|
| `--port`, `-p` | Serial port | auto-detect |
| `--auto-detect` | Scan for FT232/USB-serial device | — |
| `--baud`, `-b` | Burn baud rate | 1000000 |
| `--at-baud` | AT command baud rate | 115200 |
| `--boot-timeout` | Seconds to wait for bootloader prompt/mode banner | 30 |
| `--send-timeout` | Seconds to wait for each firmware transfer response | 120 |
| `--packet-delay-ms` | Pause between raw `fwupdata` packets | 0 |
| `--skip-zero-chunks` | Skip all-zero raw `fwupdata` chunks for sparse patch burns | — |
| `--firmware`, `-f` | CODE1 firmware (fw_update1.bin) | optional |
| `--bootloader`, `-F` | Bootloader image | optional |
| `--flashcode` | CODE2 flash image (fw_update2.bin) | optional |
| `--keyfile` | KEY file (CSV/TXT) | optional |
| `--mac` | MAC address to burn | optional |
| `--manual-mode` | Assume the chip is already at the raw bootloader prompt and use `fwupdata` | — |
| `--no-reboot` | Do not reboot/boot after download | — |
| `--serial-monitor` | Mirror bootloader TX/RX to stderr | — |
| `--json` | JSON output mode | — |
| `--log-level`, `-l` | Log level (debug/info/warn/error) | info |

### No-reboot firmware patch helper

The helper below patches known reset/WDT reboot paths in a corrected
little-endian flash dump and emits both a full image and bootloader burn images.
It does not require committing firmware blobs to git.

```bash
python tools/patch_no_reboot.py firmware_dump_le.bin

atbm6441-cli burn --manual-mode --no-reboot --serial-monitor \
  --port COM6 \
  --flashcode firmware_analysis/code2_no_reboot.bin
```

### `key` — Burn KEY data

Burns encryption keys from a CSV or hex string file to flash.

```bash
atbm6441-cli key \
  --port /dev/ttyUSB0 \
  --keyfile keys.csv \
  --key1-addr 0x008000 \
  --key2-addr 0x101000
```

### `info` — Query chip information

Sends AT commands to query chip version, SDK version, and firmware info.

```bash
# All queries
atbm6441-cli info --port /dev/ttyUSB0 all

# Specific query
atbm6441-cli info --port /dev/ttyUSB0 gmr
atbm6441-cli info --port /dev/ttyUSB0 sdk
atbm6441-cli info --port /dev/ttyUSB0 venver
atbm6441-cli info --port /dev/ttyUSB0 status
```

| Command | AT Command | Description |
|---|---|---|
| `gmr` | `AT+GMR` | Modem info |
| `sdk` | `AT+GET_SDK_VER` | SDK version |
| `venver` | `AT+VENVER` | Hardware version |
| `fwinfo` | `AT+WIFI_GET_FWINFO` | Firmware info |
| `status` | `AT+WIFI_STATUS` | WiFi status |

### `mem` — Read/write memory

Reads or writes 32-bit values to chip memory via AT commands.

```bash
# Read memory
atbm6441-cli mem r 0x16a00020 --length 4 --port /dev/ttyUSB0

# Write memory
atbm6441-cli mem w 0x100000 0xDEADBEEF --port /dev/ttyUSB0
```

### `read` — Read flash content

Reads flash content from the chip and saves to a file.

```bash
atbm6441-cli read \
  --port /dev/ttyUSB0 \
  --addr 0x000000 \
  --len 0x100000 \
  output.bin
```

### `verify` — Verify burned firmware

Reads back flash and compares checksums against the original binary.

```bash
atbm6441-cli verify \
  --port /dev/ttyUSB0 \
  --firmware fw_update1.bin
```

### `chip` — Chip information

Queries chip ID and version.

```bash
atbm6441-cli chip info --port /dev/ttyUSB0
atbm6441-cli chip flash-id --port /dev/ttyUSB0
```

## Firmware Image Layout

The ATBM6441 bootloader expects firmware images at specific flash addresses:

| Component | Address | Max Size | Description |
|---|---|---|---|
| Bootloader | `0x000000` | 48 KB | `bootloader_step1.bin` |
| KEY1 data | `0x008000` | — | Encryption key (key1) |
| KEY2 data | `0x101000` | — | Encryption key (key2) |
| CODE1 (ICCM) | `0x010000` | ~2 MB | `fw_update1.bin` — main firmware |
| CODE2 (Flash) | `0x040000` | ~2 MB | `fw_update2.bin` — flash/AP data |
| Userdata | `0x400000–0x600000` | — | MAC, efuse, calibration |

## Protocol Details

### UART Configuration

| Setting | Value |
|---|---|
| Port | Configurable (e.g. `/dev/ttyUSB0`, `COM3`) |
| Baud rate | 1,000,000 (burn) or 115,200 (AT commands) |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |

### Boot Mode Sequence

1. Open UART at 1,000,000 baud
2. Send `AT+START\r\n` → chip enters bootloader mode
3. Wait for `[ bootloader mode ]` response
4. Send `AT+SEND\r\n` → chip expects firmware data
5. Send firmware binary in 1024-byte chunks
6. Wait for `<<< download SUCCESS >>>` response
7. Send `AT+REBOOT\r\n` → chip reboots with new firmware

### AT Commands

| Command | Purpose |
|---|---|
| `AT+START` | Enter bootloader mode |
| `AT+SEND` | Start firmware data transfer |
| `AT+REBOOT` | Reboot chip after burn |
| `AT+wmem <addr> <value>` | Write 32-bit value to memory |
| `AT+WIFI_ETF_RMEM <addr> <len>` | Read bytes from memory |
| `AT+GMR` | Get modem info |
| `AT+GET_SDK_VER` | Get SDK version |
| `AT+VENVER` | Get hardware version |
| `AT+PRINT 0/1` | Enable/disable verbose output |
| `AT+WIFI_GET_FWINFO` | Get firmware info |

### Flash Register Addresses

| Address | Purpose |
|---|---|
| `0x16100008` | Reset control (0 = reset, 0xFFFFFFFF = release) |
| `0x16100074` | AHB read/write target |
| `0x1610007c` | AHB control |
| `0x161000ac` | Config register |
| `0x16101000` | Config register |
| `0x1610102c` | Config register |
| `0x16a00020`–`0x16a00040` | Chip version / ID registers |
| `0xacc0178` | Clock config (0x3400071) |

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run unit tests only (no integration)
python -m pytest tests/ -v -m "not integration"

# Run with coverage
python -m pytest tests/ -v --cov=atbm6441_cli --cov-report=term-missing
```

## Development

### Project Structure

```
atbm6441-cli/
├── src/atbm6441_cli/
│   ├── cli/
│   │   ├── __init__.py      # Entry point, argparse dispatch
│   │   └── commands/
│   │       ├── burn.py      # burn command
│   │       ├── key.py       # key command
│   │       ├── info.py      # info command
│   │       ├── mem.py       # mem command
│   │       ├── read.py      # read command
│   │       ├── verify.py    # verify command
│   │       └── chip.py      # chip command
│   ├── protocol/
│   │   ├── bootloader.py    # AT command protocol
│   │   ├── uart.py          # Serial port management
│   │   ├── flash_id.py      # JEDEC ID discovery
│   │   └── flash_reader.py  # Chunked flash read
│   ├── config.py            # INI-based config
│   └── utils/
│       └── logging.py       # Structured logging
├── tests/
│   ├── test_bootloader.py   # Protocol tests
│   ├── test_uart.py         # Serial tests
│   ├── test_cli.py          # CLI tests
│   └── test_config.py       # Config tests
├── pyproject.toml
└── README.md
```

### Adding a New Command

1. Create `src/atbm6441_cli/cli_commands/newcmd.py` with `newcmd_parser()` and `newcmd_handler()`
2. Import and register in `src/atbm6441_cli/cli/__init__.py`
3. Add tests in `tests/test_newcmd.py`

## Success Criteria

- [x] Can flash bootloader + CODE1 + CODE2 via UART at 1M baud
- [x] Verified firmware boots correctly after burn
- [x] Can read chip ID and firmware version
- [x] Can read/write flash at arbitrary addresses
- [x] Works without any proprietary DLLs
- [x] Exit codes and JSON output for CI integration
- [ ] Burn time < 30s for 1M image (pending hardware testing)

## License

MIT
