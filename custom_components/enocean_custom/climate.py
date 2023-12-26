"""Support for EnOcean climate devices."""
from __future__ import annotations

from typing import Any

import logging
import math
from datetime import datetime

from .enocean_library.utils import combine_hex
import voluptuous as vol

from homeassistant.components.climate import (
    PLATFORM_SCHEMA,
    ATTR_CURRENT_HUMIDITY,
    ATTR_CURRENT_TEMPERATURE,
    ATTR_PRESET_MODE,
    ATTR_TEMPERATURE,
    DOMAIN as CLIMATE_DOMAIN,
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
from homeassistant.helpers import entity_platform, service, entity_component
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType, EventType
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_state_change_event,
    async_track_time_interval,
)

from .const import DOMAIN, LOGGER
from .device import EnOceanEntity

DEVICE_SUPPORTED_LIST = ["SRC-D08"]
'''
Thermokon SRC-D08

Telegram from controller
EEP: 07-20-12 / A5-20-12

Data byte   Description                     Value
DB3         Control variable override       0 ... 100% <=> 0 ... 255

DB2         Fan Stage override              not used

DB1         Setpoint shift                  -10K ... +10K <=> 0 ... 255

DB0.7       Fan override Automatic          Automatic <=> 0, Override Fan DB2 <=> 1
DB0.6 0.5   Controller mode                 Automatic <=> 0b00, Heating <=> 0b01, Cooling <=> 0b10, Off <=> 0b11
DB0.4       Controller state                Automatic <=> 0, Override control variable DB3 <=> 1
DB0.3       LRN bit                         Data-Telegram <=> 1, LRN-Telegram <=> 0
DB0.2       Energy hold-off                 Occupied/Manual <=> 0b00, Unoccupied <=> 0b01, Standby <=> 0b10, Frost <=> 0b11
DB0.1 0.0   Room occupancy
'''

DEFAULT_NAME = "EnOcean Climate"
CONF_DEVICE_TYPE = "device_type"
CONF_SENDER_ID = "sender_id"
CONF_CHANNEL = "channel"
CONF_SENSOR_ENTITY_ID = "sensor_entity_id"
CONF_SENSOR_TARGET_TEMP_RANGE = "sensor_target_temperature_range"
CONF_SENSOR_TARGET_TEMP_TOLERANCE = "sensor_target_temperature_update_tolerance"
CONF_TARGET_TEMP_BASE = "target_temperature_base_value"
CONF_TARGET_TEMP_NIGHT_REDUCTION = "target_temperature_reduction_night"
CONF_TARGET_TEMP_STANDBY_REDUCTION = "target_temperature_reduction_standby"
CONF_TARGET_TEMP_COMFORT_STARTTIME = "target_temperature_comfort_start_time"
CONF_TARGET_TEMP_COMFORT_ENDTIME = "target_temperature_comfort_end_time"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_ID, default=[]): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_SENDER_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Required(CONF_DEVICE_TYPE): cv.string,
        vol.Optional(CONF_CHANNEL, default=0): cv.positive_int,
        vol.Required(CONF_SENSOR_ENTITY_ID): cv.string,
        vol.Optional(CONF_SENSOR_TARGET_TEMP_RANGE, default=5): cv.positive_int,
        vol.Optional(CONF_SENSOR_TARGET_TEMP_TOLERANCE, default=0.5): cv.positive_float,
        vol.Optional(CONF_TARGET_TEMP_BASE, default=21.0): cv.positive_float,
        vol.Optional(CONF_TARGET_TEMP_NIGHT_REDUCTION, default=4.0): cv.positive_float,
        vol.Optional(CONF_TARGET_TEMP_STANDBY_REDUCTION, default=2.0): cv.positive_float,
        vol.Optional(CONF_TARGET_TEMP_COMFORT_STARTTIME, default="8:00"): cv.string,
        vol.Optional(CONF_TARGET_TEMP_COMFORT_ENDTIME, default="23:00"): cv.string,
    }
)

def generate_unique_id(dev_id: list[int], channel: int) -> str:
    """Generate a valid unique id."""
    return f"{combine_hex(dev_id)}-{channel}"

def _migrate_to_new_unique_id(hass: HomeAssistant, dev_id, channel) -> None:
    """Migrate old unique ids to new unique ids."""
    old_unique_id = f"{combine_hex(dev_id)}"

    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id(Platform.CLIMATE, DOMAIN, old_unique_id)
    
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

_LOGGER = logging.getLogger(__name__)

def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the EnOcean climate platform."""
    dev_name = config.get(CONF_NAME)
    device_type = config.get(CONF_DEVICE_TYPE)
    sender_id = config.get(CONF_SENDER_ID)
    dev_id = config.get(CONF_ID)
    channel = config.get(CONF_CHANNEL)
    sensor_entity_id = config.get(CONF_SENSOR_ENTITY_ID)
    sensor_target_temp_range = config.get(CONF_SENSOR_TARGET_TEMP_RANGE)
    sensor_target_temp_tolerance = config.get(CONF_SENSOR_TARGET_TEMP_TOLERANCE)
    target_temp_base = config.get(CONF_TARGET_TEMP_BASE)
    target_temp_reduction_night = config.get(CONF_TARGET_TEMP_NIGHT_REDUCTION)
    target_temp_reduction_standby = config.get(CONF_TARGET_TEMP_STANDBY_REDUCTION)
    target_temperature_comfort_start_time = datetime.strptime(config.get(CONF_TARGET_TEMP_COMFORT_STARTTIME), '%H:%M')
    target_temperature_comfort_end_time = datetime.strptime(config.get(CONF_TARGET_TEMP_COMFORT_ENDTIME), '%H:%M')

    if device_type not in DEVICE_SUPPORTED_LIST:
        _LOGGER.error(f"Device '{device_type}' not supported for {DOMAIN} climate device. Supported devices are '{DEVICE_SUPPORTED_LIST}'")
        return

    _migrate_to_new_unique_id(hass, dev_id, channel)
    add_entities([EnOceanClimate(
        dev_id,
        dev_name,
        sender_id,
        channel,
        sensor_entity_id,
        sensor_target_temp_range,
        sensor_target_temp_tolerance,
        target_temp_base,
        target_temp_reduction_night,
        target_temp_reduction_standby,
        target_temperature_comfort_start_time,
        target_temperature_comfort_end_time
    )])

    #platform = entity_platform.sync_get_current_platform()
    platform = entity_platform.EntityPlatform(
        hass=hass,
        logger=_LOGGER,
        domain=CLIMATE_DOMAIN,
        platform_name=DOMAIN,
        platform=None,
        scan_interval=60,
        entity_namespace=CLIMATE_DOMAIN,
        )
    platform.async_register_entity_service('climate_teach_in_actor', {}, "teach_in_actor")

class EnOceanClimate(EnOceanEntity, ClimateEntity):
    """Representation of an EnOcean climate device."""

    def __init__(
            self,
            dev_id,
            dev_name,
            sender_id,
            channel,
            sensor_entity_id,
            sensor_target_temp_range,
            sensor_target_temp_tolerance,
            target_temp_base,
            target_temp_reduction_night,
            target_temp_reduction_standby,
            target_temperature_comfort_start_time,
            target_temperature_comfort_end_time
            ):
        """Initialize the EnOcean switch device."""
        super().__init__(dev_id, dev_name)
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._sender_id = sender_id
        self._channel = channel
        self.sensor_entity_id = sensor_entity_id
        self._target_temp_base = target_temp_base
        self._cur_temp = None
        self._target_temp = 21.0
        self._sensor_target_temp = self._target_temp
        self._sensor_target_temp_range = sensor_target_temp_range
        self._sensor_target_temp_tolerance = sensor_target_temp_tolerance
        self._target_temp_reduction_night = target_temp_reduction_night
        self._target_temp_reduction_standby = target_temp_reduction_standby
        self._comfort_temperature_start_time = target_temperature_comfort_start_time
        self._comfort_temperature_end_time = target_temperature_comfort_end_time
        self._hvac_mode = None
        self._attr_unique_id = generate_unique_id(dev_id, self._channel)

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
        """Return the name of the device if any."""
        return self.dev_name

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        return self._target_temp_base - 10.0

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        return self._target_temp_base + 10.0

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return hvac mode."""
        return self._hvac_mode

    @property
    def hvac_action(self):
        """Return the current running hvac operation if supported.

        Need to be one of CURRENT_HVAC_*.
        """
        if self._hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        #if not self._is_device_active:
        #    return HVACAction.IDLE
        return HVACAction.HEATING

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

    def sendPacket(self, data: list):
        # packet type 4BS
        command = [0xA5]
        # 4 data bytes
        command.extend(data)
        # sender ID
        command.extend(self._sender_id)
        # Checksum byte
        command.extend([0x00])
        self.send_command(command, [], 0x01)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set hvac mode."""
        if hvac_mode == HVACMode.HEAT:
            self.set_temperature(temperature=self._sensor_target_temp)
            self._hvac_mode = HVACMode.HEAT
        elif hvac_mode == HVACMode.OFF:
            self.sendPacket([0x00, 0x00, 0x00, 0b00011000])
            self._target_temp = None
            self._hvac_mode = HVACMode.OFF
        else:
            _LOGGER.error("Unrecognized hvac mode: %s", hvac_mode)
            return
        # Ensure we update the current operation after changing the mode
        self.async_write_ha_state()

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
        _LOGGER.debug(f"Set temperature of {self._attr_unique_id} to: {kwargs.get(ATTR_TEMPERATURE)}")
        self._target_temp = kwargs.get(ATTR_TEMPERATURE)
        self._hvac_mode = HVACMode.HEAT
        setPoint = round( (self._target_temp-self._target_temp_base)*12.75 + 127.5)
        if setPoint > 255:
            setPoint = 255
            _LOGGER.warning("Temperature set point greater than 255, clipping value.")
        elif setPoint < 0:
            setPoint = 0
            _LOGGER.warning("Temperature set point less than 0, clipping value.")
        self.sendPacket([0x00, 0x1F, setPoint, 0b00001000])

    @callback
    def _async_update_temp(self, state: State) -> None:
        """Update thermostat with latest state from sensor."""
        try:
            cur_temp = float(state.state)
            if not math.isfinite(cur_temp):
                raise ValueError(f"Sensor has illegal state {state.state}")
            self._cur_temp = cur_temp
            target_temp_new = (state.attributes["SetPoint"]*2/255 - 1)*self._sensor_target_temp_range + self._target_temp_base
            if abs(self._sensor_target_temp-target_temp_new) > self._sensor_target_temp_tolerance:
                self._sensor_target_temp = target_temp_new
                self.set_temperature(temperature=self._sensor_target_temp)
        except ValueError as ex:
            _LOGGER.error("Unable to update from sensor: %s", ex)

    def teach_in_actor(self) -> None:
        """Send teach-in telegram."""
        self.sendPacket([0x00, 0x00, 0x00, 0b10000000])