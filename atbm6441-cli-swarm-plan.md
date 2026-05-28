# Plan: ATBM6441 CLI Swarm Execution

**Generated**: 2026-05-27
**Plan owner**: Matt
**Source PRD**: `atbm6441-cli/PRD.md`
**Target CWD**: `/home/matteius/ATBM6441/文档资料/烧录工具/atbm6441-cli`

## Overview

Implementation plan for the ATBM6441 CLI burn tool — a cross-platform Python CLI that replaces the Windows-only Altobem GUI. Decomposed into ~52 atomic tasks across 5 waves. Foundation tasks (CLI skeleton, serial management, config) land first; protocol reverse-engineering follows; firmware burn and extended operations build on top; polish closes out.

**Execution philosophy**
- Foundation tasks (CLI skeleton, serial port, config, logging) must complete before any protocol or burn work.
- Protocol tasks (frame format, handshake, register ops) are a bridge between serial management and firmware burn.
- Burn tasks depend on the full protocol layer being in place.
- Extended operations (KEY, MAC, efuse, erase) depend on burn working.
- Polish is last.
- Each task is sized for a single agent to complete end-to-end.

## Prerequisites

- Python 3.8+ available on the target system
- `pyserial`, `click`, `tqdm` — installable via pip (no proprietary DLLs)
- Hardware: ATBM6441 EVK board with USB-serial adapter (FT232) for integration testing
- Optional: serial sniffer (e.g., `socat` or `pyserial-logger`) for packet capture during Phase 2
- Existing reference: `Altobem WIFI IOT GUI V1.0.52/` directory contains the Windows GUI binaries for protocol reference

## Dependency Graph (high-level)

```
Wave 1 — Foundation
  F1  CLI skeleton (click, project structure)
  F2  Serial port management (pyserial wrapper)
  F3  Config file support
  F4  Logging infrastructure

Wave 2 — Protocol (depends on Wave 1)
  T2.1  DLL string/symbol analysis (research, no code)
  T2.2  Iterative protocol experimentation on real hardware (research + stub code)
  T2.3  Handshake protocol (boot mode entry, Enter sequence)
  T2.4  Register read/write via UART
  T2.5  ROM code mode entry

Wave 3 — Firmware Burn (depends on Wave 2)
  T3.1  Bootloader download (fw_update1.bin)
  T3.2  Flash download (fw_update2.bin)
  T3.3  Checksum verification
  T3.4  burn command (full flow)
  T3.5  verify command
  T3.6  Progress bar during burn (tqdm)
  T3.7  Exit codes (0=success, 1=error, 2=verify-fail)

Wave 4 — Extended Operations (depends on Wave 3)
  T4.1  read / write commands
  T4.2  KEY file burn
  T4.3  MAC address burn + read
  T4.4  Efuse read/write
  T4.5  Flash erase
  T4.6  Flash address override (FR-42)
  T4.7  Flash write protection disable (FR-41)

Wave 5 — Polish (depends on Wave 4)
  T5.1  JSON output mode
  T5.2  CI-friendly logging (quiet mode)
  T5.3  Documentation (README, usage examples)
  T5.4  Packaging (setup.py / pyproject.toml)
```

---

## Foundation tasks (F) — Wave 1

### F1: CLI skeleton with click framework
- **depends_on**: []
- **location**: `src/atbm6441_cli/`, `tests/`
- **description**: Create Python package structure with `click` CLI framework. Entry point `atbm6441-cli` command. Root command with `--version`, `--help`. Subcommand scaffolding for `burn`, `verify`, `read`, `write`, `chipid`, `info`. Project layout: `src/atbm6441_cli/cli/main.py`, `src/atbm6441_cli/cli/commands/`, `src/atbm6441_cli/protocol/`, `src/atbm6441_cli/flash/`, `src/atbm6441_cli/utils/`. Include `pyproject.toml` with `click` and `tqdm` as deps.
- **validation**: `pip install -e .` then `atbm6441-cli --help` shows all subcommands. `atbm6441-cli burn --help` shows subcommand help.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `pyproject.toml` (new)
  - `src/atbm6441_cli/__init__.py` (new)
  - `src/atbm6441_cli/cli/__init__.py` (new)
  - `src/atbm6441_cli/cli/main.py` (new)
  - `src/atbm6441_cli/cli/commands/__init__.py` (new)
  - `src/atbm6441_cli/cli/commands/burn.py` (new, stub)
  - `src/atbm6441_cli/cli/commands/verify.py` (new, stub)
  - `src/atbm6441_cli/cli/commands/read.py` (new, stub)
  - `src/atbm6441_cli/cli/commands/write.py` (new, stub)
  - `src/atbm6441_cli/cli/commands/chip.py` (new, stub)
  - `src/atbm6441_cli/protocol/__init__.py` (new)
  - `src/atbm6441_cli/flash/__init__.py` (new)
  - `src/atbm6441_cli/utils/__init__.py` (new)
  - `tests/__init__.py` (new)
  - `tests/test_cli.py` (new)

### F2: Serial port management
- **depends_on**: [F1]
- **location**: `src/atbm6441_cli/protocol/uart.py`
- **description**: Implement serial port management using `pyserial`. `SerialManager` class with `open(port, baudrate)`, `close()`, `write(data)`, `read(timeout)`, `read_until(delim, timeout)`. Auto-detect FT232 devices via `pyserial` vendor ID scan. Support configurable baud rates (115200, 1000000, 1500000). Error handling for port not found, permission denied, timeout.
- **validation**: Unit tests mocking `serial.Serial`. Integration test on real hardware (if available) with loopback.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/protocol/uart.py` (new)
  - `tests/test_uart.py` (new)

### F3: Config file support
- **depends_on**: [F1]
- **location**: `src/atbm6441_cli/config.py`
- **description**: Implement config file at `~/.atbm6441-cli.ini` (INI format via Python `configparser`). Default values: `port=/dev/ttyUSB0`, `baud=1000000`, `at_baud=115200`, `boot_timeout=5`. CLI flags override config values. Support `--port`, `--baud`, `--at-baud`, `--boot-timeout` on every command.
- **validation**: Test config read/write with INI file. Test flag override precedence.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/config.py` (new)
  - `tests/test_config.py` (new)

### F4: Logging infrastructure
- **depends_on**: [F1]
- **location**: `src/atbm6441_cli/utils/logging.py`
- **description**: Structured logging with `logging` module. Levels: `debug`, `info`, `warn`, `error`. `--log-level` flag. JSON output mode via `--json` flag (emit JSON-formatted log lines to stderr). Exit code convention: 0=success, 1=error, 2=verify-fail.
- **validation**: Test log level filtering. Test JSON output format.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/utils/logging.py` (new)
  - `tests/test_logging.py` (new)

---

## Protocol Reverse-Engineering — Wave 2 (depends on F1–F4)

> **Note**: No Windows machine available to run the GUI tool for packet capture. Protocol understanding comes from analyzing the Windows DLLs (strings, symbols, function names) and iterative experimentation on real hardware.

### T2.1: DLL string/symbol analysis (research task)
- **depends_on**: [F1, F2]
- **location**: `docs/protocol-analysis.md`
- **description**: Analyze the Windows GUI binaries in `Altobem WIFI IOT GUI V1.0.52/` for protocol clues using `strings`, `nm`, `objdump`, or `readelf` on the DLLs (`etf_api.dll`, `wlan_target_multi.dll`, `spi_burn_flash.dll`, `i2c_bus.dll`). Extract: (a) string literals (protocol keywords, frame patterns like `HI_WriteRequest`, `Target_Read_Reg32`, `Target_Write_Reg32`, `atbm_fw_checksum`), (b) exported function names and signatures, (c) hardcoded constants (magic bytes, timeouts, default addresses). Also analyze `bootloader_GUI.exe` for bootloader-specific protocol details. Document all findings. This is a research task — no code written. Output is analysis document.
- **validation**: Document contains protocol string extraction results, function name maps, and inferred frame format with hex examples.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `docs/protocol-analysis.md` (new)

### T2.2: Iterative protocol experimentation (research + stub code)
- **depends_on**: [T2.1]
- **location**: `docs/protocol-analysis.md` (updated), `src/atbm6441_cli/protocol/frames.py`
- **description**: Iteratively probe the ATBM6441 chip on real hardware to discover the protocol. Steps: (a) open serial port, (b) send raw bytes matching guessed frame format from T2.1, (c) observe responses, (d) refine frame format. Start with simple operations: send `>` prompt detection, try sending register read requests with guessed msg_id/payload format, observe ACK/NACK patterns. Document each iteration. This task produces both updated protocol analysis and a working (if incomplete) frame implementation.
- **validation**: Document contains at least 3 successful probe rounds with hex captures. Frame parser can decode at least 2 known response types.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `docs/protocol-analysis.md` (updated)
  - `src/atbm6441_cli/protocol/frames.py` (new, iterative)
  - `tests/test_frames.py` (new)

### T2.3: Handshake protocol
- **depends_on**: [F2, T2.2]
- **location**: `src/atbm6441_cli/protocol/handshake.py`
- **description**: Implement chip mode entry and AT command exchange. `BootloaderEntry` class: send reset signal (or manual trigger), send `Enter` keys repeatedly, wait for `>` prompt with configurable timeout. `ATCommand` class: send AT command, parse response, handle echo. Support `--manual-mode` flag to skip auto GPIO control. Support `--boot-timeout` for Enter sequence. Implement AT command `AT+VENVER` for firmware version query.
- **validation**: Unit tests with mock serial. Integration test on real hardware: enter bootloader, send AT+VENVER, parse response.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/protocol/handshake.py` (new)
  - `tests/test_handshake.py` (new)

### T2.4: Register read/write via UART
- **depends_on**: [T2.2, T2.3]
- **location**: `src/atbm6441_cli/protocol/registers.py`
- **description**: Implement register-level operations using framed messages. `RegisterReader`: send `Target_Read_Reg32(addr)`, parse response. `RegisterWriter`: send `Target_Write_Reg32(addr, value)`, parse ACK. Implement chip ID read (read version register, return chip version string). This is the foundation for all firmware download operations.
- **validation**: Unit tests with mock serial. Integration test: read chip ID from real hardware, match expected ATBM6441 version.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/protocol/registers.py` (new)
  - `tests/test_registers.py` (new)

### T2.5: ROM code mode entry
- **depends_on**: [T2.3]
- **location**: `src/atbm6441_cli/protocol/handshake.py`
- **description**: Implement ROM code mode entry (FR-21). Same GPIO control as boot mode but with BOOT_SEL low instead of high. `RomCodeEntry` class: send reset with BOOT_SEL low, wait for ROM code prompt. Support `--manual-mode` override. This complements T2.3's bootloader entry.
- **validation**: Unit tests with mock serial. Integration test: enter ROM code mode on real hardware, verify prompt received.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/protocol/handshake.py` (updated)
  - `tests/test_handshake.py` (updated)

---

## Firmware Burn — Wave 3 (depends on T2.1–T2.4)

### T3.1: Bootloader download (fw_update1.bin)
- **depends_on**: [T2.3, T2.4]
- **location**: `src/atbm6441_cli/protocol/download.py`
- **description**: Implement first-stage firmware download: enter bootloader mode, send fw_update1.bin (ICCM/code image) to chip. Handle bootloader-specific download protocol (XMODEM or custom — per T2.1 analysis). Send file in chunks, handle ACK/NACK per chunk. Implement checksum verification after download (`atbm_fw_checksum`).
- **validation**: Unit tests with mock serial and test binary. Integration test: download fw_update1.bin to real hardware, verify checksum matches.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/protocol/download.py` (new)
  - `tests/fixtures/test_fw_update1.bin` (new, small test binary)
  - `tests/test_download.py` (new)

### T3.2: Flash download (fw_update2.bin)
- **depends_on**: [T3.1]
- **location**: `src/atbm6441_cli/protocol/download.py`
- **description**: Implement second-stage firmware download: send fw_update2.bin (flash data image) to chip. Handle flash write protocol — write data to flash at specified address, verify each block. Implement progress reporting (percentage complete).
- **validation**: Unit tests with mock serial and test binary. Integration test: download fw_update2.bin to real hardware, verify checksum matches.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/protocol/download.py` (updated)
  - `tests/fixtures/test_fw_update2.bin` (new, small test binary)
  - `tests/test_download.py` (updated)

### T3.3: Checksum verification
- **depends_on**: [T3.1, T3.2]
- **location**: `src/atbm6441_cli/protocol/checksum.py`
- **description**: Implement `atbm_fw_checksum` calculation. Verify firmware image against checksum embedded in or computed after download. Used by both download stages and the `verify` command.
- **validation**: Unit tests: checksum of known test binary matches expected value. Edge cases: empty file, single byte, large file.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/protocol/checksum.py` (new)
  - `tests/test_checksum.py` (new)

### T3.4: burn command
- **depends_on**: [T3.1, T3.2, T3.3]
- **location**: `src/atbm6441_cli/cli/commands/burn.py`
- **description**: Implement full `burn` command. Accepts `--firmware`, `--bootloader`, `--flashcode` paths. Flow: (1) open serial port, (2) enter bootloader mode, (3) read chip ID, (4) download fw_update1.bin with progress bar, (5) verify checksum, (6) download fw_update2.bin with progress bar, (7) verify checksum, (8) reset chip, (9) confirm boot. Progress bar via `tqdm`. Structured logging. Exit code 0 on success, 1 on error.
- **validation**: Integration test: burn firmware to real hardware, verify chip boots and responds to AT commands.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/cli/commands/burn.py` (updated)
  - `tests/test_burn_integration.py` (new, integration only)

### T3.5: verify command
- **depends_on**: [T3.3, T3.4]
- **location**: `src/atbm6441_cli/cli/commands/verify.py`
- **description**: Implement `verify` command. Read back flash content from chip, compare against original binary using checksum. Report pass/fail with address of any mismatch. Exit code 0=pass, 2=verify-fail.
- **validation**: Integration test: burn then verify on real hardware — should pass. Tamper test: modify binary after burn, verify should fail.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/cli/commands/verify.py` (updated)
  - `tests/test_verify.py` (new)

### T3.6: Progress bar during burn (FR-50)
- **depends_on**: [T3.4]
- **location**: `src/atbm6441_cli/utils/progress.py`
- **description**: Implement progress bar using `tqdm` for burn operations. `ProgressBar` class wraps `tqdm` with: percentage display, estimated time remaining, bytes/sec throughput. Used by burn (T3.4), read (T4.1), and write (T4.1) commands. Integrates with logging (F4) — progress updates logged at debug level.
- **validation**: Unit tests: progress bar updates at 10%, 50%, 90%, 100%. Integration test: run burn command, verify progress bar displays correctly.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/utils/progress.py` (new)
  - `src/atbm6441_cli/cli/commands/burn.py` (updated)
  - `src/atbm6441_cli/cli/commands/read.py` (updated)
  - `src/atbm6441_cli/cli/commands/write.py` (updated)
  - `tests/test_progress.py` (new)

### T3.7: Exit codes (FR-53)
- **depends_on**: [F4]
- **location**: `src/atbm6441_cli/cli/main.py`
- **description**: Implement consistent exit code convention across all commands (FR-53): 0=success, 1=error, 2=verify-fail. Centralize in `main()` dispatcher. Each command handler returns an int exit code. Error cases (port not found, protocol failure, checksum mismatch) map to appropriate codes. `--quiet` flag suppresses non-essential output for CI use.
- **validation**: Run each command, verify exit codes match expectations. Test error paths (missing port, invalid firmware) return 1. Test verify failure returns 2.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/cli/main.py` (updated)
  - `tests/test_exit_codes.py` (new)

---

## Extended Operations — Wave 4 (depends on T3.1–T3.5)

### T4.1: read / write commands
- **depends_on**: [T2.4, T3.4]
- **location**: `src/atbm6441_cli/cli/commands/read.py`, `src/atbm6441_cli/cli/commands/write.py`
- **description**: Implement `read` and `write` commands. `read --addr 0x000000 --len 0x100000 output.bin` — read flash content to file. `write --addr 0x100000 data.bin` — write binary to flash address. Use register-level read/write ops from T2.4. Progress bar for large transfers.
- **validation**: Integration test: write known data, read it back, compare.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/cli/commands/read.py` (updated)
  - `src/atbm6441_cli/cli/commands/write.py` (updated)
  - `tests/test_read_write.py` (new)

### T4.2: KEY file burn
- **depends_on**: [T3.4]
- **location**: `src/atbm6441_cli/cli/commands/burn.py`
- **description**: Implement KEY file burning via `--keyfile keys.txt`. Support CSV/TXT key format from GUI (key=value pairs, one per line). Write keys to flash userdata area or efuse as specified by protocol. Require `--force` flag.
- **validation**: Integration test: burn KEY file, read back, verify keys match.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/cli/commands/burn.py` (updated)
  - `tests/fixtures/test_keys.txt` (new)
  - `tests/test_key_burn.py` (new)

### T4.3: MAC address burn + read
- **depends_on**: [T4.1]
- **location**: `src/atbm6441_cli/cli/commands/chip.py`
- **description**: Implement MAC address operations. `burn` via `--mac aa:bb:cc:dd:ee:ff` — write MAC to efuse/flash userdata. `read-mac` — display current MAC. Require `--force` for burn. Validate MAC format (6 hex octets).
- **validation**: Integration test: burn MAC, read back, verify match. Invalid MAC format should be rejected.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/cli/commands/chip.py` (updated)
  - `tests/test_mac.py` (new)

### T4.4: Efuse read/write
- **depends_on**: [T2.4]
- **location**: `src/atbm6441_cli/flash/efuse.py`
- **description**: Implement low-level efuse operations. `--efuse-read <index>` — read efuse value at index. `--efuse-write <index> <value>` — write value to efuse index. Require `--force` for write. Efuse operations are destructive — add safety warnings.
- **validation**: Integration test: read efuse, write value (if efuse is writable), read back, verify.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/flash/efuse.py` (new)
  - `src/atbm6441_cli/cli/commands/chip.py` (updated)
  - `tests/test_efuse.py` (new)

### T4.5: Flash erase
- **depends_on**: [T3.4]
- **location**: `src/atbm6441_cli/flash/spi.py`
- **description**: Implement flash erase operations. `--erase-sector <addr>` — erase flash sector at address. `--erase-all` — erase entire flash. Require `--force` flag. Disable write protection before erase (`--no-flash-protect`).
- **validation**: Integration test: erase sector, read back should return all 0xFF.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/flash/spi.py` (new)
  - `src/atbm6441_cli/cli/commands/burn.py` (updated)
  - `tests/test_spi_erase.py` (new)

### T4.6: Flash address override (FR-42)
- **depends_on**: [T3.4]
- **location**: `src/atbm6441_cli/cli/commands/burn.py`
- **description**: Implement `--flash-addr <addr>` override for burn command (FR-42). Allow specifying an arbitrary flash address instead of the default burn address. Used to burn firmware to a non-default location. Also applies to `write` command.
- **validation**: Unit tests: address parsing (hex strings like `0x100000`). Integration test: burn to custom address, verify chip boots from that address.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/cli/commands/burn.py` (updated)
  - `src/atbm6441_cli/cli/commands/write.py` (updated)
  - `tests/test_flash_addr.py` (new)

### T4.7: Flash write protection disable (FR-41)
- **depends_on**: [T4.5]
- **location**: `src/atbm6441_cli/flash/spi.py`
- **description**: Implement flash write protection control (FR-41). `--no-flash-protect` flag on burn/write/erase commands. Read status register, clear WP bits, write status register. Re-enable protection after burn if it was previously enabled.
- **validation**: Integration test: read status register (protected), burn with `--no-flash-protect`, verify write succeeds, status register shows protection re-enabled.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/flash/spi.py` (updated)
  - `src/atbm6441_cli/cli/commands/burn.py` (updated)
  - `src/atbm6441_cli/cli/commands/write.py` (updated)
  - `tests/test_flash_protect.py` (new)

---

## Polish — Wave 5 (depends on T4.1–T4.5)

### T5.1: JSON output mode
- **depends_on**: [F4]
- **location**: `src/atbm6441_cli/utils/logging.py`, `src/atbm6441_cli/cli/main.py`
- **description**: Add `--json` flag to all commands. When enabled, emit machine-readable JSON output to stdout (or to a file via `--json-file`). Include: operation result, timing, byte counts, exit status. Structured JSON with consistent schema.
- **validation**: Run `atbm6441-cli chipid --json`, parse output as JSON, verify fields present.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/utils/logging.py` (updated)
  - `src/atbm6441_cli/cli/main.py` (updated)
  - `tests/test_json_output.py` (new)

### T5.2: CI-friendly logging (quiet mode)
- **depends_on**: [T3.7]
- **location**: `src/atbm6441_cli/utils/logging.py`, `src/atbm6441_cli/cli/main.py`
- **description**: Add `--quiet` flag to suppress non-essential output. Add `--verbose` for debug-level logging. Ensure no interactive prompts (auto-fail if port not specified and no `--auto-detect`). Exit codes handled by T3.7.
- **validation**: Run commands in a script, check exit codes. Verify no interactive prompts. Verify `--quiet` suppresses progress bar and status messages.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `src/atbm6441_cli/cli/main.py` (updated)
  - `src/atbm6441_cli/utils/logging.py` (updated)
  - `tests/test_quiet_mode.py` (new)

### T5.3: Documentation
- **depends_on**: [T3.4, T4.1–T4.5]
- **location**: `docs/`, `README.md`
- **description**: Write comprehensive README with: installation instructions, usage examples for all commands, hardware setup guide, protocol notes, troubleshooting. Document all CLI flags. Add `docs/usage-examples.md` with copy-paste examples for common workflows (burn, verify, read MAC, etc.).
- **validation**: README renders correctly on GitHub. Examples tested against actual tool output.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `README.md` (new)
  - `docs/usage-examples.md` (new)
  - `docs/hardware-setup.md` (new)
  - `docs/troubleshooting.md` (new)

### T5.4: Packaging
- **depends_on**: [F1, T5.1]
- **location**: `pyproject.toml`, `setup.py` (if needed)
- **description**: Make package pip-installable. `pyproject.toml` with: package name `atbm6441-cli`, version, description, authors, license, dependencies (`pyserial`, `click`, `tqdm`), entry point (`atbm6441-cli = atbm6441_cli.cli.main:cli`). Add `MANIFEST.in` for docs. Test `pip install .` and `atbm6441-cli --help`.
- **validation**: `pip install .` succeeds, `atbm6441-cli --help` works. `pip list` shows package.
- **status**: Not Completed
- **log**:
- **files edited/created**:
  - `pyproject.toml` (updated)
  - `MANIFEST.in` (new)
  - `tests/test_packaging.py` (new)

---

## Testing Strategy

### Unit tests (per task)
- Each task creates its own test file under `tests/`.
- Tests use `pytest` with `unittest.mock` for serial port mocking.
- No integration tests in unit test suite — those are separate.

### Integration tests
- `tests/test_burn_integration.py` — full burn flow on real hardware.
- `tests/test_read_write.py` — write/read round-trip on real hardware.
- `tests/test_verify.py` — burn + verify on real hardware.
- Integration tests are skipped in CI (`pytest.mark.integration`) and run only with `--integration` flag.

### Test fixtures
- `tests/fixtures/` directory for test binaries and captured packet samples.
- Small test binaries (100 bytes) for unit tests.
- Captured packet samples from T2.1 analysis for frame parsing tests.

---

## Risks & Mitigations (mapped to tasks)

| Risk | Impact | Mitigation | Task |
|---|---|---|---|
| Protocol is encrypted/obfuscated | High | DLL string analysis in T2.1 may reveal encryption; if so, fallback to wrapping `etf_api.dll` via `ctypes` on a Windows VM | T2.1 |
| No Windows machine for GUI packet capture | Medium | Protocol discovery via DLL analysis (T2.1) + iterative hardware probing (T2.2) | T2.1, T2.2 |
| GPIO control required for auto mode | Medium | Start with `--manual-mode`; I2C support deferred | T2.3 |
| Timing-sensitive operations fail | Medium | Configurable delays; log all timing for debugging | T2.3, T3.1 |
| Flash erase may brick device | High | Require `--force` flag; add safety checks | T4.5 |
| FT232 driver issues on Linux | Low | `pyserial` abstracts drivers; test early | F2 |

---

## Success Criteria (mapped to tasks)

- [ ] **T3.4**: Can flash fw_update1.bin + fw_update2.bin to ATBM6441 via UART at 1M baud
- [ ] **T3.5**: Verified firmware boots correctly after burn
- [ ] **T2.4**: Can read chip ID
- [ ] **T2.3**: Can read firmware version via AT command
- [ ] **T2.5**: Can enter ROM code mode
- [ ] **T4.1**: Can read/write flash at arbitrary addresses
- [ ] **T4.6**: Can override default burn address (`--flash-addr`)
- [ ] **T4.7**: Can disable flash write protection (`--no-flash-protect`)
- [ ] **T3.6**: Progress bar visible during burn
- [ ] **T3.7**: Exit codes correct (0=success, 1=error, 2=verify-fail)
- [ ] **T3.1/T3.2**: Burn time < 30s for 1M image (matching PRD NFR-05)
- [ ] **F2**: Works without any proprietary DLLs
- [ ] **T5.1**: JSON output for CI integration
- [ ] **T5.3**: README and usage examples documented
- [ ] **T5.4**: `pip install atbm6441-cli` works
