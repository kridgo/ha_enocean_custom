"""Support for EnOcean covers."""
from __future__ import annotations

import logging

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components.binary_sensor import (
    PLATFORM_SCHEMA,
)
from homeassistant.components.cover import CoverEntity, CoverEntityFeature, ATTR_POSITION
from homeassistant.const import CONF_ID, CONF_NAME, CONF_SENDER
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from .const import ENOCEAN_DONGLE, DATA_ENOCEAN, SIGNAL_SEND_MESSAGE
from .device import EnOceanEntity
from .enocean_library.protocol.constants import RORG
from .enocean_library.protocol.packet import Packet, RadioPacket

DEFAULT_NAME = "EnOcean Cover"
DEPENDENCIES = ["enocean"]

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_SENDER): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    }
)


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Cover platform for EnOcean."""
    dev_id = config.get(CONF_ID)
    dev_name = config.get(CONF_NAME)
    sender_id = config.get(CONF_SENDER)
    rorg = RORG.VLD
    rorg_func = 0x05
    rorg_type = 0x00

    add_entities([EnOceanCover(dev_id, dev_name, sender_id, rorg, rorg_func, rorg_type)])

_LOGGER = logging.getLogger(__name__)

class EnOceanCover(EnOceanEntity, CoverEntity):
    """Representation of EnOcean covers.

    Supported EEPs (EnOcean Equipment Profiles):
    - D2-05-00 (ex: Nodon SIN-2-RS-01)
    """

    def __init__(self, dev_id, dev_name, sender_id, rorg, rorg_func, rorg_type):
        """Initialize the EnOcean binary sensor."""
        super().__init__(dev_id, dev_name)
        self._sender_id = sender_id
        self._rorg = rorg
        self._rorg_func = rorg_func
        self._rorg_type = rorg_type
        self._previous_cover_position = None
        self._current_cover_position = None
        self._supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP | CoverEntityFeature.SET_POSITION

    @property
    def name(self):
        """Return the default name for the binary sensor."""
        return self.dev_name

    @property
    def supported_features(self):
        """Flag supported features."""
        return self._supported_features

    async def async_added_to_hass(self):
        """To restore state, ask cover position."""
        await super().async_added_to_hass()
        self.ask_cover_position()

    def update(self):
        """Ask cover position."""
        self.ask_cover_position()

    @property
    def current_cover_position(self):
        return self._current_cover_position

    @property
    def is_opening(self):
        if self._current_cover_position == None or self._previous_cover_position == None:
            return None
        if self._previous_cover_position == self._current_cover_position:
            return None
        return self._previous_cover_position < self._current_cover_position

    @property
    def is_closing(self):
        if self._current_cover_position == None or self._previous_cover_position == None:
            return None
        if self._previous_cover_position == self._current_cover_position:
            return None
        return self._previous_cover_position > self._current_cover_position

    @property
    def is_closed(self):
        if self._current_cover_position == None:
            return None
        return self._current_cover_position == 0

    @property
    def sender_id(self):
        if self._sender_id != None:
            return self._sender_id
        return self.hass.data[DATA_ENOCEAN][ENOCEAN_DONGLE].base_id

    def open_cover(self, **kwargs):
        kwargs[ATTR_POSITION] = 100
        self.set_cover_position(**kwargs)

    def close_cover(self, **kwargs):
        kwargs[ATTR_POSITION] = 0
        self.set_cover_position(**kwargs)

    def stop_cover(self, **kwargs):
        _LOGGER.debug("Stopping %s", self.dev_name)
        packet = Packet.create(
            # TODO: Not sure of this?
            packet_type=0x01,
            rorg=self._rorg,
            rorg_func=self._rorg_func,
            rorg_type=self._rorg_type,
            direction=None,
            command=2,
            destination=self.dev_id,
            sender=self.sender_id,
        )
        dispatcher_send(self.hass, SIGNAL_SEND_MESSAGE, packet)

    def set_cover_position(self, **kwargs):
        if ATTR_POSITION in kwargs:
            position = 100 - kwargs[ATTR_POSITION]
            _LOGGER.debug("Sending position for %s: %d", self.dev_name, position)
            packet = Packet.create(
                # TODO: Not sure of this?
                packet_type=0x01,
                rorg=self._rorg,
                rorg_func=self._rorg_func,
                rorg_type=self._rorg_type,
                direction=None,
                command=1,
                destination=self.dev_id,
                sender=self.sender_id,
                learn=False,
                POS=position
            )
            dispatcher_send(self.hass, SIGNAL_SEND_MESSAGE, packet)

    def ask_cover_position(self):
        _LOGGER.debug("Asking position for %s", self.dev_name)
        packet = Packet.create(
            # TODO: Not sure of this?
            packet_type=0x01,
            rorg=self._rorg,
            rorg_func=self._rorg_func,
            rorg_type=self._rorg_type,
            direction=None,
            command=3,
            destination=self.dev_id,
            sender=self.sender_id,
            learn=False
        )
        dispatcher_send(self.hass, SIGNAL_SEND_MESSAGE, packet)

    def value_changed(self, packet):
        """Update the internal state of the switch."""
        if isinstance(packet, RadioPacket) and packet.sender == self.dev_id and packet.rorg == RORG.VLD:
            packet.select_eep(self._rorg_func, self._rorg_type)
            packet.parse_eep()
            raw_pos = packet.parsed['POS']['raw_value']
            if raw_pos == 127:
                _LOGGER.debug("/!\ Unkown position received for %s (%d)", self.dev_name, raw_pos)
                self._current_cover_position = None
            else:
                _LOGGER.debug("New position received for %s: %d", self.dev_name, (100 - raw_pos))
                self._previous_cover_position = self._current_cover_position
                self._current_cover_position = 100 - raw_pos

