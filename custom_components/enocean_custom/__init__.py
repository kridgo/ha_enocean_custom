"""Support for EnOcean devices."""
import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_DEVICE
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.dispatcher import dispatcher_send

from .const import DATA_ENOCEAN, DOMAIN, ENOCEAN_DONGLE, LOGGER, SIGNAL_SEND_MESSAGE
from .dongle import EnOceanDongle
from .enocean_library.protocol.packet import Packet

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({vol.Required(CONF_DEVICE): cv.string})}, extra=vol.ALLOW_EXTRA
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the EnOcean component."""
    # support for text-based configuration (legacy)
    if DOMAIN not in config:
        return True

    if hass.config_entries.async_entries(DOMAIN):
        # We can only have one dongle. If there is already one in the config,
        # there is no need to import the yaml based config.
        return True

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=config[DOMAIN]
        )
    )

    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up an EnOcean dongle for the given entry."""
    enocean_data = hass.data.setdefault(DATA_ENOCEAN, {})
    usb_dongle = EnOceanDongle(hass, config_entry.data[CONF_DEVICE])
    await usb_dongle.async_setup()
    enocean_data[ENOCEAN_DONGLE] = usb_dongle

    def send_packet(call):
        """service call"""
        LOGGER.debug(f"service called with data {call.data}")

        packet_type = call.data.get("packet_type",0x01)
        optional = call.data.get("optional",[])
        data = call.data.get("data",[0xD5, 0x00])
        status = call.data.get("status",[0x00])
        sender_id = call.data.get("sender_id",[0xFF, 0xFF, 0xFF, 0xFF])

        packet_data = data
        packet_data.extend(sender_id)
        packet_data.extend(status)
        packet = Packet(packet_type, packet_data, optional)
        dispatcher_send(hass, SIGNAL_SEND_MESSAGE, packet)

    hass.services.async_register(DOMAIN, "send_packet", send_packet)

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload ENOcean config entry."""

    enocean_dongle = hass.data[DATA_ENOCEAN][ENOCEAN_DONGLE]
    enocean_dongle.unload()
    hass.data.pop(DATA_ENOCEAN)

    return True
