# EnOcean Custom

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

> Custom EnOcean integration for Home Assistant, fork of the official integration.

## Background
The official EnOcean integration for Home Assistant is currently not being extended by new functionality as the code needs a major refactory. Pull requests to add new sensors etc. are [not being accepted](https://github.com/home-assistant/core/pull/86461#discussion_r1084908489). That is why this custom integration was created. Also, the EnOcean protocol library being used by Home Assistant seems to be abandoned, that is why a fork is included in this custom integration.

## Installation
1. [Install HACS](https://hacs.xyz/docs/setup/download/)
2. Open HACS in your Home Assistant installation
3. Add the repository URL to your HACS installation: `Integrations > Three Dots > Custom integrations > Add URL`
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
```
switch:
  - platform: enocean_custom
    name: switch_livingroom
    switch_type: RPS    # emulate doouble rocker push button
    channel: 0          # 0 for left rocker, 1 for right rocker
    id: [0xFF, 0xD9, 0x04, 0x81]
```
To teach-in the switch to your EnOcean device, put the device in learning mode and toggle the state of the switch entity in Home Assistant.

### Bug fixes
- Exception to handle parsing of malformed packets: With the official protocol library, the EnOcean integration would crash when receiving a malformed package. In practice, this happens every few weeks to months for some installations. An exception handler was added to drop malformed packages, see [PR for original protocol library](https://github.com/kipe/enocean/pull/138)
