# EWD108 GNSS Home Assistant Integration

Custom Home Assistant integration for EBYTE EWD108-GN0x Modbus GNSS devices.

This integration polls the EWD108 over Modbus (TCP, RTU-over-TCP, or serial RTU), reads the RMC payload, decodes it, and exposes GNSS data as Home Assistant entities.

Supported device family:

- EWD108-GN03
- EWD108-GN03B
- EWD108-GN04
- EWD108-GN05
- EWD108-GN06B

Protocol reference used in this repository:

- [docs/EWD108-GN0x_Series_UserManual_CN_V1.0.md](docs/EWD108-GN0x_Series_UserManual_CN_V1.0.md)

## Features

Requires **Home Assistant 2026.10 or newer**.

- Uses Home Assistant's shared Modbus unit API for TCP, serial RTU and RTU over TCP.
- Reads one complete 35-register RMC frame per poll instead of independent coordinate registers.
- Defaults to **30-second polling** with two retries on read/parse failure (1-second then 2-second waits).
- Validates checksum, coordinate format/bounds, date/time freshness and plausible movement.
- Publishes latitude and longitude together through a native GPS device tracker.
- Reports invalid fixes as unavailable GPS, preserving the raw frame and a diagnostic rejection reason.
- Automatically reconnects through HA's connection manager; unloading releases only this integration's unit.
- Provides a settings flow for changing polling and connection settings without recreating entities.
- Optionally updates HA's location only from accepted GPS fixes.

A frame older than 30 seconds or more than 5 seconds in the future is rejected.
Jump filtering permits up to 250 km/h plus a 100 m tolerance, using GNSS time
and the last accepted fix. Invalid readings do not replace that baseline.
Coherent readings on the equator or prime meridian remain valid; only the
zero/zero sentinel is always rejected. Invalid-fix responses do not trigger
communication retries: they are successful reads of a receiver without a fix.

See [migration from YAML polling](docs/shared-modbus-migration.md) before
activating this version on an existing Modbus gateway.

## Installation

### Option 1: HACS (recommended)

1. Open HACS in Home Assistant.
2. Add this repository as a custom repository (category: Integration).
3. Install EWD108 GNSS.
4. Restart Home Assistant.

### Option 2: Manual

1. Copy [custom_components/ewd108](custom_components/ewd108) into your Home Assistant config folder under custom_components.
2. Restart Home Assistant.

Expected resulting path:

- &lt;config&gt;/custom_components/ewd108

## Hardware and connectivity

Typical setup:

- EWD108 RS485 variant
- TCP/RS485 gateway (common) or USB-to-RS485 adapter (optional)
- 5-24 V power supply for EWD108
- GNSS antenna connected to SMA ANT

Example TCP gateway configuration:

```yaml
- name: hub_1
  type: rtuovertcp
  host: 192.168.1.10
  port: 502
  delay: 1
  timeout: 1
```

Default EWD108 serial settings (when using serial transport):

- 9600 baud
- 8 data bits
- no parity
- 1 stop bit

## Home Assistant setup

1. Go to Settings -> Devices and Services.
1. Click Add Integration.
1. Search for EWD108 GNSS.
1. Choose hub source:

- Use existing hub from your configuration.yaml modbus section (if found).
- Or continue with manual setup.

1. Fill connection and device fields.

- Connection type (RTU over TCP, TCP, or Serial RTU)
- Host/TCP port (for network transports)
- Serial port (for serial transport)
- Delay (for network transports)
- Baud rate
- Data bits
- Parity
- Stop bits
- Modbus slave ID
- Polling interval (seconds)
- Modbus timeout (seconds)
- Set Home Assistant location (optional)
- Location update threshold (meters)

## Entities

### Binary sensor

- Fix valid: ON when RMC status is valid (A), OFF when invalid (V).

### Sensors

- Latitude
- Longitude
- Speed (km/h)
- Course
- Timestamp (UTC)
- Raw RMC sentence
- Geohash
- Position text (formatted coordinates)

## Notes

- All position entities consume one validated RMC sample.
- Timestamp is UTC from the device data.
- Home Assistant location update runs only when:
  - fix is valid
  - coordinates exist
  - movement since last applied location exceeds threshold

## Troubleshooting

- Check serial wiring (A/B lines, ground reference, power).
- Verify serial settings match the device configuration.
- Confirm slave ID is correct.
- Verify that your RS485 adapter is exposed to Home Assistant.
- Enable debug logs for this integration in [config/configuration.yaml](config/configuration.yaml):

```yaml
logger:
  default: info
  logs:
    custom_components.ewd108: debug
```

## Development

- Main integration code: [custom_components/ewd108](custom_components/ewd108)
- Device documentation: [docs/EWD108-GN0x_Series_UserManual_CN_V1.0.md](docs/EWD108-GN0x_Series_UserManual_CN_V1.0.md)
- Development helper scripts: [scripts](scripts)

## License

See [LICENSE](LICENSE).
