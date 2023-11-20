"""Support for EnOcean climate devices."""
from __future__ import annotations

from typing import Any

import logging
import math

from .enocean_library.utils import combine_hex
import voluptuous as vol

from homeassistant.components.climate import (
    PLATFORM_SCHEMA,
    ATTR_CURRENT_HUMIDITY,
    ATTR_CURRENT_TEMPERATURE,
    ATTR_PRESET_MODE,
    ATTR_TEMPERATURE,
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_NONE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    CONF_ID,
    CONF_NAME,
    EVENT_HOMEASSISTANT_START,
    Platform,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature
)
from homeassistant.core import HomeAssistant, callback, State, CoreState
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType, EventType
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_state_change_event,
    async_track_time_interval,
)

from .const import DOMAIN, LOGGER
from .device import EnOceanEntity

DEFAULT_NAME = "EnOcean Climate"
CONF_SENDER_ID = "sender_id"
CONF_CHANNEL = "channel"
CONF_SENSOR_ENTITY_ID = "target_sensor"
CONF_SENSOR_TARGET_TEMP_RANGE = "target_sensor_setpoint_range"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_ID, default=[]): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_SENDER_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Required(CONF_CHANNEL): cv.positive_int,
        vol.Required(CONF_SENSOR_ENTITY_ID): cv.string,
        vol.Optional(CONF_SENSOR_TARGET_TEMP_RANGE, default=5): cv.positive_int,
    }
)

def generate_unique_id(dev_id: list[int], channel: int) -> str:
    """Generate a valid unique id."""
    return f"{combine_hex(dev_id)}-{channel}"

def _migrate_to_new_unique_id(hass: HomeAssistant, dev_id, channel) -> None:
    """Migrate old unique ids to new unique ids."""
    old_unique_id = f"{combine_hex(dev_id)}"

    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id(Platform.SWITCH, DOMAIN, old_unique_id)

    if entity_id is not None:
        new_unique_id = generate_unique_id(dev_id, channel)
        try:
            ent_reg.async_update_entity(entity_id, new_unique_id=new_unique_id)
        except ValueError:
            LOGGER.warning(
                "Skip migration of id [%s] to [%s] because it already exists",
                old_unique_id,
                new_unique_id,
            )
        else:
            LOGGER.debug(
                "Migrating unique_id from [%s] to [%s]",
                old_unique_id,
                new_unique_id,
            )

def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the EnOcean climate platform."""
    sender_id = config.get(CONF_SENDER_ID)
    channel = config.get(CONF_CHANNEL)
    dev_name = config.get(CONF_NAME)
    dev_id = config.get(CONF_ID)
    sensor_entity_id = config.get(CONF_SENSOR_ENTITY_ID)
    sensor_target_temp_range = config.get(CONF_SENSOR_TARGET_TEMP_RANGE)

    _migrate_to_new_unique_id(hass, dev_id, channel)
    add_entities([EnOceanClimate(sender_id, dev_id, dev_name, channel, sensor_entity_id, sensor_target_temp_range)])

_LOGGER = logging.getLogger(__name__)

class EnOceanClimate(EnOceanEntity, ClimateEntity):
    """Representation of an EnOcean climate device."""

    def __init__(self, sender_id, dev_id, dev_name, channel, sensor_entity_id, sensor_target_temp_range):
        """Initialize the EnOcean switch device."""
        super().__init__(dev_id, dev_name)
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._sender_id = sender_id
        self._channel = channel
        self.sensor_entity_id = sensor_entity_id
        self._target_temp_base = 20.0
        self._cur_temp = None
        self._target_temp = None
        self._sensor_target_temp_range = sensor_target_temp_range
        self._sensor_temp_tolerance = 0.5
        self._attr_unique_id = f"{combine_hex(dev_id)}"

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        # Add listener
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self.sensor_entity_id], self._async_sensor_changed
            )
        )

        @callback
        def _async_startup(*_):
            """Init on startup."""
            sensor_state = self.hass.states.get(self.sensor_entity_id)
            if sensor_state and sensor_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                self._async_update_temp(sensor_state)
                self.async_write_ha_state()

        if self.hass.state == CoreState.running:
            _async_startup()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)

    @property
    def name(self):
        """Return the device name."""
        return self._target_temp_base + 10.0

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        return self._target_temp_base - 10.0

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        return 30.5

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return hvac mode."""
        return None

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available hvac modes."""
        return [HVACMode.OFF, HVACMode.HEAT]

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return the list of supported features."""
        supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
        return supported_features

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        return self._target_temp

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._cur_temp
    
    async def _async_sensor_changed(
        self, event: EventType[EventStateChangedData]
    ) -> None:
        """Handle temperature changes."""
        new_state = event.data["new_state"]
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        self._async_update_temp(new_state)
        self.async_write_ha_state()

    def set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        _LOGGER.info('Set temperature to: ' + str(kwargs.get(ATTR_TEMPERATURE)))
        self._target_temp = kwargs.get(ATTR_TEMPERATURE)
        setPoint = round( (self._target_temp-self._target_temp_base)*12.75 + 127.5)
        if setPoint > 255:
            setPoint = 255
            _LOGGER.warning("Temperature set point greater than 255, clipping value.")
        elif setPoint < 0:
            setPoint = 0
            _LOGGER.warning("Temperature set point less than 0, clipping value.")
        command = [0xA5, 0x00, 0x1F, setPoint, 0x08]
        command.extend(self._sender_id)
        command.extend([0x00])
        self.send_command(command, [], 0x01)

    @callback
    def _async_update_temp(self, state: State) -> None:
        """Update thermostat with latest state from sensor."""
        try:
            cur_temp = float(state.state)
            if not math.isfinite(cur_temp):
                raise ValueError(f"Sensor has illegal state {state.state}")
            self._cur_temp = cur_temp
            target_temp = (state.state.attributes.SetPoint*2/255 - 1)*self._sensor_target_temp_range + self._target_temp_base
            if abs(target_temp-self._target_temp) > self._sensor_temp_tolerance:
                self.set_temperature(temperature=target_temp)
        except ValueError as ex:
            _LOGGER.error("Unable to update from sensor: %s", ex)