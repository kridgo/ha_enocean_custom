# EnOcean Custom

[![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

> Custom EnOcean integration for Home Assistant, fork of the official integration.

## Background
The official EnOcean integration for Home Assistant is currently not being extended by new functionality as the code needs a major refactory. Pull requests to add new sensors etc. are [not being accepted](https://github.com/home-assistant/core/pull/86461#discussion_r1084908489). That is why this custom integration was created. Also, the EnOcean protocol library being used by Home Assistant seems to be abandoned, that is why a fork is included in this custom integration.

## Description
This custom integration uses the code of the [official EnOcean integration](https://www.home-assistant.io/integrations/enocean/) and the [EnOcean library, `kipe/enocean`](https://github.com/kipe/enocean) and implements bug fixes and new functionalities:

### Binary sensors
Binary sensors do not only trigger events but also have a state variable which may be `On` or `Off`. The state attributes `Onoff` and `Which` have been added to identify which pushbutton is being pressed. The state attribute `Repeated telegram` indicates if the received telegram was received by an EnOcean repeater.

### Support for shutter contacts
Add support for shutter contacts with EnOcean Equipment Profile EEP: D5-00-01. The sensor state can be `Open` or `Closed`.

### Bug fixes
- Exception to handle parsing of malformed packets: With the official protocol library, the EnOcean integration would crash when receiving a malformed package. In practice, this happens every few weeks to months for some installations. An exception handler was added to drop malformed packages, see [PR for original protocol library](https://github.com/kipe/enocean/pull/138)
