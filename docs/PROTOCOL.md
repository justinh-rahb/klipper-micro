# Klipper protocol — subset used by klipper-micro

This document covers the slice of the Klipper host↔MCU protocol that
klipper-micro implements. The complete protocol is documented upstream at
[`Klipper Protocol.md`](https://github.com/Klipper3d/klipper/blob/master/docs/Protocol.md).

## Wire format

Every frame on the wire looks like:

```
+--------+--------+----------------------+--------+--------+--------+
| length |  seq   |   payload (1..59)    |    crc16-ccitt  |  0x7e  |
| 1 byte | 1 byte |     N bytes          |     2 bytes     | 1 byte |
+--------+--------+----------------------+--------+--------+--------+
```

- **length** — total frame length in bytes, including header and trailer. Min 5, max 64.
- **seq** — `(seq_number & 0x0f) | 0x10`. The high nibble bit (`0x10` =
  `MESSAGE_DEST`) is always set; the low nibble is the 4-bit sequence number.
  Direction (host→MCU vs MCU→host) is inferred from context — both sides set the bit.
- **payload** — one or more back-to-back VLQ-encoded messages.
- **crc16-ccitt** — computed over `[length, seq, ...payload]`, big-endian.
- **sync byte** — `0x7e`. Marks frame boundary; also used to resync after CRC errors.

VLQ (variable-length quantity) integers use 7-bit chunks with the high bit set on
all bytes except the last. Same encoding as `klippy/msgproto.py:PT_uint32.encode`.

## Identify dialogue

The first thing the host does is fetch the MCU's *data dictionary* — a
zlib-compressed JSON blob describing every command the firmware understands
along with its assigned message ID. The host can't decode anything else until
this completes.

```
host                                 MCU
 ─── identify offset=0 count=40 ──→
 ←─── identify_response offset=0 data=...  (40 bytes of blob)
 ─── identify offset=40 count=40 ──→
 ←─── identify_response offset=40 data=...
 ... repeats until response data is empty ...
```

The IDs for `identify` and `identify_response` themselves are hardcoded
defaults (msgid 1 and 0 respectively); everything else is learned at runtime.

## Clock synchronisation

The MCU's clock is the reference for all timed operations (PWM schedule
points, ADC sample times). The host runs a continuous linear regression to
map host monotonic time → MCU clock.

```
host                                 MCU
 ─── get_uptime ──→                       (seed 64-bit clock)
 ←─── uptime high=H clock=L
 ─── get_clock ──→  (×8 over 400ms)       (prime the regression)
 ←─── clock clock=C
 ... then periodic get_clock every ~1s for life of the connection ...
```

The regression uses an exponentially-weighted moving average (`DECAY = 1/30`)
plus a minimum-RTT tracker (with aging). Math is taken verbatim from
[`vendor/klipper/klippy/clocksync.py`](../vendor/klipper/klippy/clocksync.py).

## Configuration phase

After identify + clock sync, the host tells the MCU what hardware to set up:

```
allocate_oids count=N                     # reserve N object IDs
config_pwm_out oid=0 pin=PA1 cycle_ticks=72000 value=0 default_value=0 max_duration=216000
config_analog_in oid=1 pin=PA2
... etc ...
finalize_config crc=0xDEADBEEF            # CRC of all preceding config commands
```

The MCU rejects any further config commands after `finalize_config`. Once
finalised, the host can issue runtime commands (`queue_pwm_out`,
`query_analog_in`, etc.).

## Runtime commands

| Command | Purpose | When sent |
|---|---|---|
| `queue_pwm_out oid clock value` | Schedule a PWM change at a given MCU clock | Each PID tick → 0..255 byte |
| `set_pwm_out pin cycle_ticks value` | Immediate PWM change, no OID | Rarely; debugging |
| `query_analog_in oid clock sample_ticks ...` | Begin periodic ADC sampling | Once per thermistor at startup |
| `emergency_stop` | Stop all output immediately | Safety violation |
| `clear_shutdown` | Resume after an emergency stop | User-initiated recovery |

## What we don't use

- `queue_step`, `set_next_step_dir`, `reset_step_clock` — motion only
- `config_stepper`, `config_trsync` — no kinematics
- `config_endstop`, `endstop_home` — no homing
- `config_thermocouple_max31856` etc. — only `config_analog_in` for now
- `config_spi`, `config_i2c` — only direct GPIO peripherals initially
- Anything CAN-related — UART only

These are all *available* through the same protocol; we simply don't drive
them. The handshake learns about them all but the host code doesn't reference
them.

## References

- [Klipper3d/klipper/docs/Protocol.md](https://github.com/Klipper3d/klipper/blob/master/docs/Protocol.md) — official protocol spec
- [`klippy/msgproto.py`](../vendor/klipper/klippy/msgproto.py) — VLQ encoding, identify parsing
- [`klippy/serialhdl.py`](../vendor/klipper/klippy/serialhdl.py) — reference host implementation
- [`klippy/chelper/serialqueue.c`](../vendor/klipper/klippy/chelper/serialqueue.c) — C frame queue (what we replace)
- [`klippy/chelper/msgblock.c`](../vendor/klipper/klippy/chelper/msgblock.c) — C frame check / VLQ
- [`src/basecmd.c`](../vendor/klipper/src/basecmd.c) — MCU-side base commands
- [`src/pwmcmds.c`](../vendor/klipper/src/pwmcmds.c) — MCU-side PWM commands
