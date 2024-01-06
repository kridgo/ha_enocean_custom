# EnOcean Custom

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

> Custom EnOcean integration for Home Assistant, fork of the official integration.

## Background

The official EnOcean integration for Home Assistant is currently not being extended by new functionality as the code needs a major refactory. Pull requests to add new sensors etc. are [not being accepted](https://github.com/home-assistant/core/pull/86461#discussion_r1084908489). That is why this custom integration was created. Also, the EnOcean protocol library being used by Home Assistant seems to be abandoned, that is why a fork is included in this custom integration.

## Installation

1. [Install HACS](https://hacs.xyz/docs/setup/download/)
2. Open HACS in your Home Assistant installation
3. Add the repository URL to your HACS installation as [custom repository](https://hacs.xyz/docs/faq/custom_repositories): `Integrations > Three Dots > Custom integrations > Add URL`
4. Install `EnOcean Custom`

## Description

This custom integration uses the code of the [official EnOcean integration](https://www.home-assistant.io/integrations/enocean/) and the [EnOcean library, `kipe/enocean`](https://github.com/kipe/enocean) and implements bug fixes and new functionalities. To use EnOcean devices with this integration, specify the key `- platform: enocean_custom` instead of `- platform: enocean` when defining an EnOcean device in your `configuration.yaml`

### Binary sensors

Binary sensors do not only trigger events but also have a state variable which may be `On` or `Off`. The state attributes `Onoff` and `Which` have been added to identify which pushbutton is being pressed. The state attribute `Repeated telegram` indicates if the received telegram was received by an EnOcean repeater.

### Support for shutter contacts

Add support for shutter contacts with EnOcean Equipment Profile EEP: D5-00-01. The sensor state can be `Open` or `Closed`.

### Switches

Switches can be used to emulate physical pushbuttons to control actors for light etc. This way you can send commands from Home Assistant to your EnOcean devices. Each switch needs its own unique EnOcean identifier (ID). The IDs can not be set randomly but depend on the base ID of your EnOcean dongle, see [this community thread](https://community.home-assistant.io/t/enocean-switch/1958/36) for more information.
To emulate double rocker push buttons, the keywords `switch_type` and `channel` are being used. The definition of a switch may look like this:

```yaml
switch:
  - platform: enocean_custom
    name: switch_livingroom
    switch_type: RPS    # emulate doouble rocker push button
    channel: 0          # 0 for left rocker, 1 for right rocker
    id: [0xFF, 0xD9, 0x04, 0x81]
```

To teach-in the switch to your EnOcean device, put the device in learning mode and toggle the state of the switch entity in Home Assistant.

### Climate device

The custom integration adds support for heating controller Thermokon SRC-D08. The climate entity takes temperature readings from a sensor entity and sends target temperature commands to the heating controller.
Currently supported HVAC modes are `off` and `heat` with preset modes `comfort`, `sleep` and `away`.

Configuration variables:

- `device_type`: Device type of the heating controller. Currently only `"SRC-D08"` is supported.
- `name`: entity name
- `id`: EnOcean ID to send temperature set point commands to the heating controller. Must fit to your [dongle's base ID](https://community.home-assistant.io/t/enocean-switch/1958/36). Commands replicate EnOcean room operating panel telegrams and use EEP A5-10-06 format.
- `id_switch`: EnOcean ID to send digital switch commands to the heating controller. Must fit to your [dongle's base ID](https://community.home-assistant.io/t/enocean-switch/1958/36).
- `sensor_entity_id`: Entity ID of the temperature sensor. Expects an [EnOcean temperature sensor](https://www.home-assistant.io/integrations/enocean/#temperature-sensor), but you may use any entity that provides the measured temperature as state and the state attributes `slideSwitch` and `setPoint`. Explanation:
  - `slideSwitch`: Set to preset mode comfort if equals `1` and preset mode sleep if equals `0`
  - `setPoint`: Value in the range of `0...255` that represents the target temperature set by the room operating panel. Set to constant value if not needed.
- `target_temperature_base_value`: Base value for comfort temperatur, default: `21`. Make sure to program the heating controller accordingly.
- `sensor_target_temperature_range`: Target temperature allowed range, default: `10`. Controls minimum and maximum target temperature values. Make sure to program the heating controller accordingly.
  - Minimum target temperature: `target_temperature_base_value - sensor_target_temperature_range`
  - Maximum target temperature: `target_temperature_base_value + sensor_target_temperature_range`
- `target_temperature_reduction_night`: Offset for night time reduction of target temperature. Make sure to program the heating controller accordingly.
  - Night time absolute temperature: `target_temperature_base_value - target_temperature_reduction_night`
- `temperature_frost_protection`: Target temperature for frost protection, this value will be commanded when the climate entity is switched to HVAC mode `off`. Make sure to program the heating controller accordingly.
- `command_frequency`: Heating controller require periodic sending of commands, otherwise the actor will switch to contingency operating mode, default: `minutes: 17`
- Heating controller PI parameter: The heating controller `SRC-D08` does not send status telegrams, so there is no information of the current valve position (which is internally calculated by a PI control law). To provide the controller output to Home Assistant, the integration calculates the controller output based on the provided controller parameters:
  - `pi_control_Kp`: Parameter for the proportional controller (`%/K`), default: `5`. Make sure to program the heating controller accordingly.
  - `pi_control_Tn`: Parameter for the integral controller (`min`), default: `240`. Make sure to program the heating controller accordingly.

Example definition of a climate entity:

```yaml
climate:
  - platform: enocean_custom
    name: heating_controller_livingroom
    device_type: "SRC-D08"
    id: [0x0F, 0x53, 0xD6, 0x83]
    id_switch: [0x12, 0x34, 0x56, 0x78]
    sensor_entity_id: "sensor.temperature_livingroom"
    target_temperature_base_value: 21
    target_temperature_reduction_night: 5
    sensor_target_temperature_range: 10
    temperature_frost_protection: 8
    command_frequency:
      minutes: 20
    pi_control_Kp: 5
    pi_control_Tn: 240
```

#### Teach-In

In order for the heating controller to accept commands received by the climate entity, you need to teach-in the corresponding EnOcean ID. The integration provides entity services to do so. First, you will need to put the heating controller into learning mode, afterwards run the service.

Teach-in the temperature sensor for entity `climate.heating_controller_livingroom`:

```yaml
service: enocean_custom.climate_teach_in_actor
target:
  entity_id:
    - climate.heating_controller_livingroom
```

Repeat the procedure to theach-in the digital switch sensor to the heating controller.

Teach-in the digital switch sensor for entity `climate.heating_controller_livingroom`:

```yaml
service: enocean_custom.climate_teach_in_actor
target:
  entity_id:
    - climate.heating_controller_livingroom
```

### Integration services

The integration provides the service `send_packet` to send an arbitrary radio telegrams.

Configuration variables:

- `packet_type`: packet type, 1 is normal packet type. Check `enocean_library/protocol/constants.py` for valid packet types.
- `data`: data of the radio packet. The first byte indicates packet type, e.g. `0xA5` for `4BS` packets.
- `optional`: optional data attached to the data
- `status`: status byte of telegram. Used to indicate repeater status of telegram, checksum etc.
- `sender_id`: EnOcean ID used as sender of the telegram. Must fit to your [dongle's base ID](https://community.home-assistant.io/t/enocean-switch/1958/36). 

Example service call:

```yaml
service: enocean_custom.send_packet
data:
  packet_type: 1
  optional: []
  data: [0xA5, 0xFF, 0xFF, 0xFF, 0xFF]
  status: 1
  sender_id: [0xFF, 0xFF, 0xFF, 0xFF]
```

### Bug fixes

- Exception to handle parsing of malformed packets: With the official protocol library, the EnOcean integration would crash when receiving a malformed package. In practice, this happens every few weeks to months for some installations. An exception handler was added to drop malformed packages, see [PR for original protocol library](https://github.com/kipe/enocean/pull/138)
