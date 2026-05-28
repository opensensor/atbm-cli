# PRD: ATBM6441 CLI Burn Tool

## 1. Overview

A lightweight, cross-platform CLI tool for flashing firmware to AltoBeam ATBM6441 WiFi IoT chips via UART. Replaces the Windows-only Altobem WIFI IOT GUI with a simpler, scriptable command-line interface.

**Goal**: Enable firmware burn, read, write, and verify operations on Linux (with macOS/Windows support as stretch goals) using only standard serial port access — no proprietary DLLs required.

---

## 2. Problem Statement

| Aspect | Current (GUI) | Desired (CLI) |
|---|---|---|
| Platform | Windows only (MFC GUI, proprietary DLLs) | Linux-first, cross-platform |
| Dependencies | `ftd2xx.dll`, `etf_api.dll`, `wlan_target_multi.dll`, `spi_burn_flash.dll`, `i2c_bus.dll` + VC++ runtime | `pyserial` (or C `termios`) — zero proprietary deps |
| Automation | Manual GUI clicks, batch mode requires MES integration | Scriptable, pipe-friendly, exit codes |
| Transparency | Black-box DLLs, no source access | Open, inspectable, hackable |
| CI/CD | Impossible to integrate | Can run in build pipelines |

---

## 3. Users & Use Cases

| User | Use Case |
|---|---|
| **Firmware engineer** | Flash a new firmware image to a dev board, verify it boots |
| **Production test** | Burn firmware + MAC + keys on a test jig, log pass/fail |
| **CI pipeline** | Automated firmware flash as part of build verification |
| **Reverse engineer** | Inspect and understand the UART burn protocol step by step |

---

## 4. Functional Requirements

### 4.1 Core Burn Operations

| ID | Requirement | Notes |
|---|---|---|
| FR-01 | **`burn`** — Flash firmware images to the chip via UART | Accepts `--firmware`, `--bootloader`, `--flashcode` paths |
| FR-02 | **`verify`** — Read back and checksum-compare burned firmware | Compares against original binary |
| FR-03 | **`read`** — Read flash content to a file | `atbm6441-cli read --addr 0x000000 --len 0x100000 output.bin` |
| FR-04 | **`write`** — Write a binary to a specific flash address | `atbm6441-cli write --addr 0x100000 data.bin` |
| FR-05 | **`chipid`** — Read chip ID / version register | Prints chip version string |
| FR-06 | **`info`** — Query firmware version via AT command | Sends `AT+VENVER` or equivalent |

### 4.2 Serial Port Configuration

| ID | Requirement | Notes |
|---|---|---|
| FR-10 | Configurable serial port (`--port /dev/ttyUSB0`) | Default: prompt user |
| FR-11 | Configurable burn baud rate (`--baud 1000000`) | Default: 1000000; supports 115200, 1500000 |
| FR-12 | Configurable AT baud rate (`--at-baud 115200`) | Separate from burn baud |
| FR-13 | Auto-detect serial port (`--auto-detect`) | Scan for FT232 / USB-serial devices |

### 4.3 Chip Mode Control

| ID | Requirement | Notes |
|---|---|---|
| FR-20 | **Boot mode** — Enter bootloader via BOOT_SEL high + reset | Requires GPIO control (CBUS/I2C) or manual |
| FR-21 | **ROM Code mode** — Enter ROM code via BOOT_SEL low + reset | Same GPIO control |
| FR-22 | Manual mode override (`--manual-mode`) | Skip auto GPIO control; user handles reset manually |
| FR-23 | Timeout for bootloader entry (`--boot-timeout 5`) | Seconds to wait for `>` prompt |

### 4.4 Key / MAC / Efuse Operations

| ID | Requirement | Notes |
|---|---|---|
| FR-30 | Burn KEY file (`--keyfile keys.txt`) | Support CSV/TXT key format from GUI |
| FR-31 | Burn MAC address (`--mac aa:bb:cc:dd:ee:ff`) | Write to efuse / flash userdata |
| FR-32 | Read MAC address (`--read-mac`) | Display current MAC |
| FR-33 | Efuse read/write (`--efuse-read`, `--efuse-write`) | Low-level efuse access |

### 4.5 Flash Operations

| ID | Requirement | Notes |
|---|---|---|
| FR-40 | Erase flash sector (`--erase-sector 0x000000`) | Erase before burn if needed |
| FR-41 | Flash status register control (`--no-flash-protect`) | Disable write protection |
| FR-42 | Burn to arbitrary address (`--flash-addr 0x100000`) | Override default burn address |

### 4.6 Output & Logging

| ID | Requirement | Notes |
|---|---|---|
| FR-50 | Progress bar or percentage during burn | Visual feedback |
| FR-51 | Structured log output (`--log-level debug|info|warn|error`) | Default: info |
| FR-52 | JSON output mode (`--json`) | Machine-readable output for CI |
| FR-53 | Exit codes: 0=success, 1=error, 2=verify-fail | Standard convention |

### 4.7 Configuration

| ID | Requirement | Notes |
|---|---|---|
| FR-60 | Config file (`~/.atbm6441-cli.ini` or `.atbmrc`) | Persist port, baud, mode settings |
| FR-61 | Override config via CLI flags (`--port`, `--baud`, etc.) | Flags take precedence |

---

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-01 | **Language**: Python 3.8+ (fast iteration for protocol reverse-engineering) |
| NFR-02 | **Dependencies**: Only `pyserial`, `click` (CLI framework), `tqdm` (progress) |
| NFR-03 | **Cross-platform**: Linux primary; macOS / Windows secondary |
| NFR-04 | **No proprietary dependencies**: No `ftd2xx.dll`, no `etf_api.dll` — use standard `termios` / `pyserial` |
| NFR-05 | **Performance**: Full 1M burn in < 30s at 1M baud (matching GUI performance) |
| NFR-06 | **Safety**: Require explicit `--force` for destructive operations (erase, efuse write) |

---

## 6. Protocol Understanding (Current State)

Based on reverse-engineering the Windows GUI binaries:

| Component | Role |
|---|---|
| `etf_api.dll` | Chip-level operations: register read/write, memory read/write, efuse, SPI, download firmware |
| `wlan_target_multi.dll` | Transport layer: UART / USB / SDIO / I2C target creation and communication |
| `spi_burn_flash.dll` | SPI flash operations: erase, write, read, status register |
| `i2c_bus.dll` | GPIO/CBUS control via I2C (for BOOT_SEL, PWR_ON control on test jig) |

### Known Protocol Details

1. **UART transport**: Standard RS-232 over USB-serial (FT232), configurable baud
2. **Bootloader handshake**: Send `Enter` repeatedly while resetting chip → bootloader echoes `>`
3. **Message framing**: `HI_WriteRequest: MsgId: 0x%x size: %d` — custom binary protocol with message IDs
4. **Firmware download**: Two-stage — `fw_update1.bin` (ICCM/code) then `fw_update2.bin` (flash data)
5. **Checksum verification**: `atbm_fw_checksum` after each download stage
6. **Register operations**: `Target_Write_Reg32`, `Target_Read_Reg32` for chip registers
7. **Bus modes**: UART (primary), USB, SDIO, I2C — tool focuses on UART first

### Unknown (Needs Packet Capture)

- Exact message frame format (header, payload, footer, CRC)
- MsgId values and their meanings
- ACK/NACK protocol details
- Bootloader-specific download protocol (XMODEM? custom?)
- Efuse write protocol details

---

## 7. Architecture (Tentative)

```
atbm6441-cli (Python)
├── cli/
│   ├── main.py          # Entry point, click commands
│   ├── commands/
│   │   ├── burn.py      # burn, verify, read, write
│   │   ├── chip.py      # chipid, info
│   │   └── config.py    # config file handling
├── protocol/
│   ├── uart.py          # Serial port management
│   ├── handshake.py     # Boot mode entry, AT command exchange
│   ├── frames.py        # Message framing / unframing
│   └── download.py      # Firmware download logic
├── flash/
│   ├── spi.py           # SPI flash operations
│   └── efuse.py         # Efuse operations
├── utils/
│   ├── progress.py      # Progress bar
│   └── logging.py       # Structured logging
└── tests/
    ├── test_uart.py
    ├── test_frames.py
    └── fixtures/        # Test binaries, captured packets
```

---

## 8. Development Phases

### Phase 1: Foundation (Week 1-2)
- [ ] CLI skeleton with `click` framework
- [ ] Serial port management (open, close, read, write)
- [ ] Chip mode entry (manual reset + Enter key sequence)
- [ ] Basic AT command exchange (version query)
- [ ] `chipid` and `info` commands working

### Phase 2: Protocol Reverse-Engineering (Week 2-4)
- [ ] Packet capture of GUI burn session (using serial monitor)
- [ ] Frame format analysis
- [ ] Implement message framing/unframing
- [ ] Handshake protocol implementation
- [ ] Register read/write via UART

### Phase 3: Firmware Burn (Week 4-6)
- [ ] Bootloader download (fw_update1.bin)
- [ ] Flash download (fw_update2.bin)
- [ ] Checksum verification
- [ ] `burn` command with progress bar
- [ ] `verify` command

### Phase 4: Extended Operations (Week 6-8)
- [ ] Flash read/write (`read`, `write` commands)
- [ ] KEY file burn
- [ ] MAC address burn
- [ ] Efuse operations
- [ ] Flash erase

### Phase 5: Polish (Week 8-9)
- [ ] Config file support
- [ ] JSON output mode
- [ ] CI-friendly logging
- [ ] Documentation (README, usage examples)
- [ ] Packaging (pip installable)

---

## 9. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Proprietary protocol is encrypted or obfuscated | High | Capture GUI traffic first; if encrypted, may need to wrap `etf_api.dll` via `ctypes` as fallback |
| GPIO control (CBUS/I2C) required for auto mode | Medium | Start with manual mode (`--manual-mode`); add I2C support later via `python-i2c-tools` |
| FT232 driver differences on Linux vs Windows | Low | `pyserial` abstracts this; test with actual hardware early |
| Timing-sensitive operations may fail | Medium | Add configurable delays; log all timing for debugging |
| Flash erase/write protection may brick device | High | Require `--force` flag; add safety checks |

---

## 10. Success Criteria

- [ ] Can flash `fw_update1.bin` + `fw_update2.bin` to ATBM6441 via UART at 1M baud
- [ ] Verified firmware boots correctly after burn
- [ ] Can read chip ID and firmware version
- [ ] Can read/write flash at arbitrary addresses
- [ ] Burn time comparable to GUI (< 30s for 1M image)
- [ ] Works without any proprietary DLLs
- [ ] Exit codes and JSON output for CI integration

---

## 11. Out of Scope (Future)

- MES integration (existing GUI has this; CLI can add later)
- USB / SDIO transport (UART only for v1)
- Calibration / RF testing (separate tool needed)
- Batch production mode with jig control (Phase 4+ if needed)
- GUI / web interface
