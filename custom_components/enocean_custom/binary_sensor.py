"""Support for EnOcean binary sensors."""
from __future__ import annotations

from enocean.utils import combine_hex
import voluptuous as vol

from homeassistant.components.binary_sensor import (
    DEVICE_CLASSES_SCHEMA,
    PLATFORM_SCHEMA,
    BinarySensorEntity,
)
from homeassistant.const import CONF_DEVICE_CLASS, CONF_ID, CONF_NAME
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .device import EnOceanEntity

DEFAULT_NAME = "EnOcean binary sensor"
DEPENDENCIES = ["enocean"]
EVENT_BUTTON_PRESSED = "button_pressed"

ATTR_ONOFF = "OnOff"
ATTR_WHICH = "Which"
ATTR_REPEATED_TELEGRAM = "Repeated telegram"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_DEVICE_CLASS): DEVICE_CLASSES_SCHEMA,
    }
)


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Binary Sensor platform for EnOcean."""
    dev_id = config.get(CONF_ID)
    dev_name = config.get(CONF_NAME)
    device_class = config.get(CONF_DEVICE_CLASS)

    add_entities([EnOceanBinarySensor(dev_id, dev_name, device_class)])


class EnOceanBinarySensor(EnOceanEntity, BinarySensorEntity):
    """Representation of EnOcean binary sensors such as wall switches.

    Supported EEPs (EnOcean Equipment Profiles):
    - F6-02-01 (Light and Blind Control - Application Style 2)
    - F6-02-02 (Light and Blind Control - Application Style 1)
    """

    def __init__(self, dev_id, dev_name, device_class):
        """Initialize the EnOcean binary sensor."""
        super().__init__(dev_id, dev_name)
        self._device_class = device_class
        self.which = -1
        self.onoff = -1
        self.repeated_telegram = -1
        self._attr_unique_id = f"{combine_hex(dev_id)}-{device_class}"

    @property
    def name(self):
        """Return the default name for the binary sensor."""
        return self.dev_name

    @property
    def device_class(self):
        """Return the class of this sensor."""
        return self._device_class

    @property
    def extra_state_attributes(self):
        """Return entity specific state attributes."""
        self._attrs = {
            ATTR_ONOFF: self.onoff,
            ATTR_WHICH: self.which,
            ATTR_REPEATED_TELEGRAM: self.repeated_telegram,
        }
        return self._attrs

    def value_changed(self, packet):
        """Fire an event with the data that have changed.

        This method is called when there is an incoming packet associated
        with this platform.

        Example packet data:
        - 2nd button pressed
            ['0xf6', '0x10', '0x00', '0x2d', '0xcf', '0x45', '0x30']
        - button released
            ['0xf6', '0x00', '0x00', '0x2d', '0xcf', '0x45', '0x20']
        """
        # Energy Bow
        pushed = None
        
        # take first byte for pushed status
        if packet.data[6]//16 == 3:
            pushed = 1
        elif packet.data[6]//16 == 2:
            pushed = 0

        # take second byte for repeated status
        self.repeated_telegram = packet.data[6]%16

        # set state
        if pushed == 1:
            self._attr_is_on = True
        elif pushed == 0:
            self._attr_is_on = False

        self.schedule_update_ha_state()

        action = packet.data[1]
        if action == 0x70:
            self.which = 0
            self.onoff = 0
        elif action == 0x50:
            self.which = 0
            self.onoff = 1
        elif action == 0x30:
            self.which = 1
            self.onoff = 0
        elif action == 0x10:
            self.which = 1
            self.onoff = 1
        elif action == 0x37:
            self.which = 10
            self.onoff = 0
        elif action == 0x15:
            self.which = 10
            self.onoff = 1
        self.hass.bus.fire(
            EVENT_BUTTON_PRESSED,
            {
                "name": self.dev_name,
                "id": self.dev_id,
                "pushed": pushed,
                "which": self.which,
                "onoff": self.onoff,
                "repeated_telegram": self.repeated_telegram,
            },
        )
