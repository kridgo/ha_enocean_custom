"""Constants for the ENOcean integration."""
import logging

from homeassistant.const import Platform

DOMAIN = "enocean_custom"
DATA_ENOCEAN = "enocean_custom"
ENOCEAN_DONGLE = "dongle"

ERROR_INVALID_DONGLE_PATH = "invalid_dongle_path"

SIGNAL_RECEIVE_MESSAGE = "enocean_custom.receive_message"
SIGNAL_SEND_MESSAGE = "enocean_custom.send_message"

LOGGER = logging.getLogger(__package__)

PLATFORMS = [
    Platform.LIGHT,
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.SWITCH,
]
