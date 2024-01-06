"""Support for EnOcean climate devices."""
from __future__ import annotations

from typing import Any

import logging
import time
import math
import random
from datetime import datetime, timedelta

from .enocean_library.utils import combine_hex
import voluptuous as vol

from homeassistant.components.climate import (
    PLATFORM_SCHEMA,
    ATTR_CURRENT_TEMPERATURE,
    ATTR_PRESET_MODE,
    ATTR_TEMPERATURE,
    DOMAIN as CLIMATE_DOMAIN,
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_SLEEP,
    PRESET_AWAY,
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
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers import entity_platform, service, entity_component
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType, EventType
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_state_change_event,
    async_track_time_interval,
    async_track_point_in_time,
)

from .const import DOMAIN, LOGGER
from .device import EnOceanEntity

DEVICE_SUPPORTED_LIST = ["SRC-D08"]
'''
Thermostat messages EEP A5-10-06
DB3: not used
DB2: Set point 0...255
DB1: Temperature 255...0 0...+40
DB0.7...4 not used (=0)
DB0.3 LRN bit
DB0.2...0.1 Not used (=0)
DB0.0 Slide switch 0=Night, 1=Day
'''

DEFAULT_NAME = "EnOcean Climate"
CONF_DEVICE_TYPE = "device_type"
CONF_SENDER_ID_SWITCH = "id_switch"
CONF_SENSOR_ENTITY_ID = "sensor_entity_id"
CONF_SENSOR_TARGET_TEMP_FROST_PROTECTION = "temperature_frost_protection"
CONF_SENSOR_TARGET_TEMP_RANGE = "sensor_target_temperature_range"
CONF_SENSOR_TARGET_TEMP_TOLERANCE = "sensor_target_temperature_update_tolerance"
CONF_TARGET_TEMP_BASE = "target_temperature_base_value"
CONF_TARGET_TEMP_NIGHT_REDUCTION = "target_temperature_reduction_night"
CONF_COMMAND_FREQUENCY = "command_frequency"
CONF_PI_CONTROL_KP = "pi_control_Kp"
CONF_PI_CONTROL_TN = "pi_control_Tn"

ATTR_PI_CONTROL_OUTPUT = "PI_control_output"
ATTR_PI_CONTROL_UNIT = "PI_control_unit"
ATTR_TEMPERATURE_COMFORT = "temperature_comfort"
ATTR_TEMPERATURE_SLEEP = "temperature_sleep"
ATTR_TEMPERATURE_AWAY =  "temperature_away"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_ID, default=[]): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_SENDER_ID_SWITCH): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Required(CONF_DEVICE_TYPE): cv.string,
        vol.Required(CONF_SENSOR_ENTITY_ID): cv.string,
        vol.Optional(CONF_SENSOR_TARGET_TEMP_FROST_PROTECTION, default=8.0): cv.positive_float,
        vol.Optional(CONF_SENSOR_TARGET_TEMP_RANGE, default=5): cv.positive_int,
        vol.Optional(CONF_SENSOR_TARGET_TEMP_TOLERANCE, default=0.5): cv.positive_float,
        vol.Optional(CONF_TARGET_TEMP_BASE, default=21.0): cv.positive_float,
        vol.Optional(CONF_TARGET_TEMP_NIGHT_REDUCTION, default=4.0): cv.positive_float,
        vol.Optional(CONF_COMMAND_FREQUENCY, default="00:17:00"): cv.positive_time_period,
        vol.Optional(CONF_PI_CONTROL_KP, default=5.0): cv.positive_float,
        vol.Optional(CONF_PI_CONTROL_TN, default=240.0): cv.positive_float,
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

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the EnOcean climate platform."""

    await async_setup_reload_service(hass, DOMAIN, [Platform.CLIMATE])

    dev_name = config.get(CONF_NAME)
    device_type = config.get(CONF_DEVICE_TYPE)
    sender_id_switch = config.get(CONF_SENDER_ID_SWITCH)
    dev_id = config.get(CONF_ID)
    sensor_entity_id = config.get(CONF_SENSOR_ENTITY_ID)
    target_temp_frost_protection = config.get(CONF_SENSOR_TARGET_TEMP_FROST_PROTECTION)
    sensor_target_temp_range = config.get(CONF_SENSOR_TARGET_TEMP_RANGE)
    sensor_target_temp_tolerance = config.get(CONF_SENSOR_TARGET_TEMP_TOLERANCE)
    target_temp_base = config.get(CONF_TARGET_TEMP_BASE)
    target_temp_reduction_night = config.get(CONF_TARGET_TEMP_NIGHT_REDUCTION)
    command_frequency = config.get(CONF_COMMAND_FREQUENCY)
    pi_control_Kp = config.get(CONF_PI_CONTROL_KP)
    pi_control_Tn = config.get(CONF_PI_CONTROL_TN)

    if device_type not in DEVICE_SUPPORTED_LIST:
        _LOGGER.error(f"Device '{device_type}' not supported for {DOMAIN} climate device. Supported devices are '{DEVICE_SUPPORTED_LIST}'")
        return

    _migrate_to_new_unique_id(hass, dev_id, 0)
    add_entities([EnOceanClimate(
        dev_id,
        dev_name,
        sender_id_switch,
        sensor_entity_id,
        target_temp_frost_protection,
        sensor_target_temp_range,
        sensor_target_temp_tolerance,
        target_temp_base,
        target_temp_reduction_night,
        command_frequency,
        pi_control_Kp,
        pi_control_Tn,
    )])

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
    platform.async_register_entity_service('climate_teach_in_actor_switch', {}, "teach_in_actor_switch")

class EnOceanClimate(EnOceanEntity, ClimateEntity, RestoreEntity):
    """Representation of an EnOcean climate device."""

    def __init__(
            self,
            dev_id,
            dev_name,
            sender_id_switch,
            sensor_entity_id,
            target_temp_frost_protection,
            sensor_target_temp_range,
            sensor_target_temp_tolerance,
            target_temp_base,
            target_temp_reduction_night,
            command_frequency,
            pi_control_Kp,
            pi_control_Tn,
            ):
        """Initialize the EnOcean switch device."""
        super().__init__(dev_id, dev_name)
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._sender_id = dev_id
        self._sender_id_switch = sender_id_switch
        self.sensor_entity_id = sensor_entity_id
        self._target_temp_base = target_temp_base
        self._attr_current_temperature = None
        self._attr_target_temp = None
        self._attr_target_temp_comfort = None
        self._attr_target_temp_sleep = None
        self._attr_target_temp_away = None
        self._target_temp_frost_protection = target_temp_frost_protection
        self._sensor_target_temp = None
        self._sensor_target_temp_range = sensor_target_temp_range
        self._sensor_target_temp_tolerance = sensor_target_temp_tolerance
        self._target_temp_reduction_night = target_temp_reduction_night
        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
        self._attr_hvac_mode = None
        self._attr_preset_mode = PRESET_NONE
        self._attr_preset_modes = [PRESET_BOOST, PRESET_COMFORT, PRESET_SLEEP, PRESET_AWAY]
        self._attr_unique_id = generate_unique_id(dev_id, 0)
        self._command_frequency = command_frequency
        self._pi_control_Kp = pi_control_Kp
        self._pi_control_Tn = pi_control_Tn
        self._attr_pi_control_output = None
        self._attr_pi_control_unit = "%"
        self._pi_control_error = 0
        self._pi_control_update_time = datetime.now()
        self._pi_control_integrator_state = None
        
    async def _async_create_timer(self, time=None):
        async_track_time_interval(
                self.hass, self._async_control_heating, self._command_frequency
            )

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        # Add listener
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self.sensor_entity_id], self._async_sensor_changed
            )
        )

        # Add timer to periodically send commands to heating actor
        # periodic commands are needed, otherwise the actor will switch to contingency operating mode
        # wait for random time before enabling time interval, so that events for different entities will not fire all at once
        random.seed(self._attr_unique_id)   # initialize random generator with different seed for each entity
        self.async_on_remove(
            async_track_point_in_time(
                    self.hass, self._async_create_timer, datetime.now() + timedelta( seconds = random.uniform(0,self._command_frequency.total_seconds()) )
                )
        )

        @callback
        async def _async_startup(*_):
            """Init on startup."""
            sensor_state = self.hass.states.get(self.sensor_entity_id)
            if sensor_state and sensor_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                await self._async_get_sensor_update(sensor_state)
                self.async_write_ha_state()

        # Check If we have an old state
        if (old_state := await self.async_get_last_state()) is not None:
            # If we have no initial temperature, restore
            if self._attr_target_temp is None:
                # If we have a previously saved temperature
                if old_state.attributes.get(ATTR_TEMPERATURE) is None:
                    self._attr_target_temp = self._target_temp_base
                    _LOGGER.warning(
                        "Undefined target temperature, falling back to %s",
                        self._attr_target_temp,
                    )
                else:
                    self._attr_target_temp = float(old_state.attributes[ATTR_TEMPERATURE])
                if old_state.attributes.get(ATTR_TEMPERATURE_COMFORT) is None:
                    self._attr_target_temp_comfort = self._target_temp_base
                    _LOGGER.warning(
                        "Undefined target temperature for preset comfort, falling back to %s",
                        self._attr_target_temp_comfort,
                    )
                else:
                    self._attr_target_temp_comfort = float(old_state.attributes[ATTR_TEMPERATURE_COMFORT])
                if old_state.attributes.get(ATTR_TEMPERATURE_SLEEP) is None:
                    self._attr_target_temp_sleep = self._target_temp_base - 5
                    _LOGGER.warning(
                        "Undefined target temperature for preset sleep, falling back to %s",
                        self._attr_target_temp_sleep,
                    )
                else:
                    self._attr_target_temp_sleep = float(old_state.attributes[ATTR_TEMPERATURE_SLEEP])
                if old_state.attributes.get(ATTR_TEMPERATURE_AWAY) is None:
                    self._attr_target_temp_away = self._target_temp_base - 5
                    _LOGGER.warning(
                        "Undefined target temperature for preset away, falling back to %s",
                        self._attr_target_temp_away,
                    )
                else:
                    self._attr_target_temp_away = float(old_state.attributes[ATTR_TEMPERATURE_AWAY])
            if (
                self._attr_preset_modes
                and old_state.attributes.get(ATTR_PRESET_MODE) in self._attr_preset_modes
            ):
                self._attr_preset_mode = old_state.attributes.get(ATTR_PRESET_MODE)
            if self._attr_hvac_mode is None and old_state.state:
                self._attr_hvac_mode = old_state.state
            if self._attr_pi_control_output is None:
                if old_state.attributes.get(ATTR_PI_CONTROL_OUTPUT) is None:
                    self._attr_pi_control_output = 0.0
                    _LOGGER.warning(
                        "Undefined PI control output, falling back to %s",
                        self._attr_pi_control_output,
                    )
                else:
                    self._attr_pi_control_output = float(old_state.attributes[ATTR_PI_CONTROL_OUTPUT])
                self._pi_control_integrator_state = self._attr_pi_control_output
        else:
            # No previous state, try and restore defaults
            if self._attr_target_temp is None:
                self._attr_target_temp = self._target_temp_base
            _LOGGER.warning(
                "No previously saved temperature, setting to %s", self._attr_target_temp
            )
            if self._attr_target_temp_comfort is None:
                self._attr_target_temp_comfort = self._target_temp_base
            _LOGGER.warning(
                "No previously saved temperature for preset comfort, setting to %s", self._attr_target_temp_comfort
            )
            if self._attr_target_temp_sleep is None:
                self._attr_target_temp_sleep = self._target_temp_base - 5
            _LOGGER.warning(
                "No previously saved temperature for preset sleep, setting to %s", self._attr_target_temp_sleep
            )
            if self._attr_target_temp_away is None:
                self._attr_target_temp_away = self._target_temp_base - 5
            _LOGGER.warning(
                "No previously saved temperature for preset away, setting to %s", self._attr_target_temp_away
            )
            if self._attr_preset_mode is PRESET_NONE:
                self._attr_preset_mode = PRESET_COMFORT
            _LOGGER.warning(
                "No previously saved preset mode, setting to %s", self._attr_preset_mode
            )
            if self._attr_pi_control_output is None:
                self._attr_pi_control_output = 0.0
            _LOGGER.warning(
                "No previously saved PI controller output, setting to %s", self._attr_pi_control_output
            )
            if self._pi_control_integrator_state is None:
                self._pi_control_integrator_state = 0.0
            _LOGGER.warning(
                "No previously saved PI integrator state, setting to %s", self._pi_control_integrator_state
            )

        # Set default state to off
        if self._attr_hvac_mode in [None, STATE_UNKNOWN, STATE_UNAVAILABLE]:
            self._attr_hvac_mode = HVACMode.OFF

        if self.hass.state == CoreState.running:
            await _async_startup()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)

    @property
    def name(self):
        """Return the name of the device if any."""
        return self.dev_name

    @property
    def extra_state_attributes(self):
        """Return entity specific state attributes."""
        self._attrs = {
            ATTR_PI_CONTROL_OUTPUT: round(self._attr_pi_control_output),
            ATTR_PI_CONTROL_UNIT: self._attr_pi_control_unit,
            ATTR_TEMPERATURE_COMFORT: self._attr_target_temp_comfort,
            ATTR_TEMPERATURE_SLEEP: self._attr_target_temp_sleep,
            ATTR_TEMPERATURE_AWAY: self._attr_target_temp_away,
        }
        return self._attrs
        
    @property
    def hvac_action(self):
        """Return the current running hvac operation if supported.

        Need to be one of CURRENT_HVAC_*.
        """
        if self._attr_pi_control_output < 5:
            # consider controller output less than 5% as idle
            return HVACAction.IDLE
        if self._attr_hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        return HVACAction.HEATING
    
    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        if self._attr_hvac_mode == HVACMode.OFF:
            return self._target_temp_frost_protection
        return self._attr_target_temp

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        if self._attr_hvac_mode == HVACMode.OFF:
            return self._target_temp_frost_protection
        elif self._attr_preset_mode == PRESET_BOOST:
            return self.max_temp
        return self._target_temp_base - 10.0

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        if self._attr_hvac_mode == HVACMode.OFF:
            return self._target_temp_frost_protection
        return self._target_temp_base + 10.0

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set hvac mode."""
        if hvac_mode == HVACMode.HEAT:
            self._attr_hvac_mode = HVACMode.HEAT
        elif hvac_mode == HVACMode.OFF:
            self._attr_hvac_mode = HVACMode.OFF
        else:
            _LOGGER.error("Unrecognized hvac mode: %s", hvac_mode)
            return
        await self._async_control_heating()
        # Ensure we update the current operation after changing the mode
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        if not self._attr_hvac_mode == HVACMode.OFF:
            # only update target_temp from UI when mode other than OFF
            self._attr_target_temp = temperature
            await self._async_control_heating()
            self.async_write_ha_state()

    async def _async_sensor_changed(
        self, event: EventType[EventStateChangedData]
    ) -> None:
        """Handle temperature changes."""
        new_state = event.data["new_state"]
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        await self._async_get_sensor_update(new_state)

    @callback
    async def _async_get_sensor_update(self, state: State) -> None:
        """Update thermostat with latest state from sensor."""
        try:
            _LOGGER.debug(f"Received sensor update for {self.dev_name} with temp {state.state}°C, setPoint {state.attributes['SetPoint']}, SlideSwitch {state.attributes['SlideSwitch']}")
            # get temperature
            cur_temp = float(state.state)
            if not math.isfinite(cur_temp):
                raise ValueError(f"Sensor has illegal state {state.state}")
            self._attr_current_temperature = cur_temp
            
            # get target temperature from setPoint
            target_temp_new = (state.attributes["SetPoint"]*2/255 - 1)*self._sensor_target_temp_range + self._target_temp_base
            slideSwitch = state.attributes["SlideSwitch"]
            if not slideSwitch:
                # slideSwitch set to night mode / temperature reduction
                target_temp_new = max(target_temp_new - self._target_temp_reduction_night, self.min_temp)
            if self._sensor_target_temp is None:
                # first sensor update after restart, save sensor value but do not overwrite target temperature of climate entity
                self._sensor_target_temp = target_temp_new
            
            if abs(self._sensor_target_temp-target_temp_new) > self._sensor_target_temp_tolerance:
                # SetPoint deviation in update greater than threshold, update climate entity with new target temperature
                self._sensor_target_temp = target_temp_new
                self._attr_hvac_mode = HVACMode.HEAT
                self._attr_target_temp = target_temp_new
                if slideSwitch:
                    self._attr_preset_mode = PRESET_COMFORT
                else:
                    self._attr_preset_mode = PRESET_SLEEP
            
            await self._async_control_heating()
            self.async_write_ha_state()
        except ValueError as ex:
            _LOGGER.error("Unable to update from sensor: %s", ex)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        if preset_mode not in (self.preset_modes or []):
            raise ValueError(
                f"Got unsupported preset_mode {preset_mode}. Must be one of"
                f" {self.preset_modes}"
            )
        if self._attr_hvac_mode == HVACMode.HEAT:
            if preset_mode == self._attr_preset_mode:
                # I don't think we need to call async_write_ha_state if we didn't change the state
                return
            
            # save target temperature of current preset
            if self._attr_preset_mode == PRESET_COMFORT:
                self._attr_target_temp_comfort = self._attr_target_temp
            if self._attr_preset_mode == PRESET_SLEEP:
                self._attr_target_temp_sleep = self._attr_target_temp
            if self._attr_preset_mode == PRESET_AWAY:
                self._attr_target_temp_away = self._attr_target_temp
            
            # set preset mode
            if preset_mode == PRESET_COMFORT:
                self._attr_target_temp = self._attr_target_temp_comfort
                self._attr_preset_mode = PRESET_COMFORT
            if preset_mode == PRESET_SLEEP:
                self._attr_target_temp = self._attr_target_temp_sleep
                self._attr_preset_mode = PRESET_SLEEP
            if preset_mode == PRESET_AWAY:
                self._attr_target_temp = self._attr_target_temp_away
                self._attr_preset_mode = PRESET_AWAY
            if preset_mode == PRESET_BOOST:
                self._attr_target_temp = self.max_temp
                self._attr_preset_mode = PRESET_BOOST
            await self._async_control_heating()
            self.async_write_ha_state()

    async def _async_control_heating(self, time=None):
        """Calculate controller commands and send to actor"""
        periodic = ""
        if time is not None:
            #_LOGGER.debug(f"Update for {self.dev_name} invoked by periodic command")
            periodic = " invoked by periodic command"
        _LOGGER.debug(f"Update for {self.dev_name}{periodic}, hvac_mode: {self._attr_hvac_mode}, preset_mode: {self._attr_preset_mode}, target_temperature: {self._attr_target_temp}.")

        # set target temperature depending on mode
        if self._attr_hvac_mode == HVACMode.OFF:
            target_temp = self._target_temp_frost_protection
        else:
            target_temp = self._attr_target_temp

        # Update controller state
        ## integrator state based on previous error
        cur_time = datetime.now()
        pi_control_timedelta = (cur_time - self._pi_control_update_time).total_seconds()/60
        self._pi_control_update_time = cur_time
        # integrator anti-wind-up
        if self._attr_pi_control_output >= 100 or self._attr_pi_control_output <= 0:
            anti_wind_up = 0
        else:
            anti_wind_up = 1
        self._pi_control_integrator_state = self._pi_control_integrator_state + pi_control_timedelta * self._pi_control_Kp * anti_wind_up * self._pi_control_error
        ## new error
        self._pi_control_error = target_temp - self._attr_current_temperature
        self._attr_pi_control_output = min(max(self._pi_control_Kp * ( self._pi_control_error + 1/self._pi_control_Tn * self._pi_control_integrator_state ), 0), 100)

        # Send command to heating actor
        ## thermostat packet
        ### calculate set point from target temperature: min_temp...max_temp -> 0...255
        setPoint = round( (target_temp-self._target_temp_base)*12.75 + 127.5)
        if setPoint > 255:
            setPoint = 255
            _LOGGER.info("Temperature set point greater than 255, clipping value.")
        elif setPoint < 0:
            setPoint = 0
            if not self._attr_hvac_mode == HVACMode.OFF:
                _LOGGER.info("Temperature set point less than 0, clipping value.")

        ### calculate temperature in protocol format: 0...+40°C -> 255...0
        cur_temp_protocol = 255 - round( 6.375 * self._attr_current_temperature )
        if cur_temp_protocol > 255:
            cur_temp_protocol = 255
            _LOGGER.info("Current temperature protocol value greater than 255, clipping value.")
        elif cur_temp_protocol < 0:
            cur_temp_protocol = 0
            _LOGGER.info("Current temperature protocol value less than 0, clipping value.")
        self.sendPacket([0x00, setPoint, cur_temp_protocol, 0b00001001])
        
        ## switch sensor packet
        if (self._attr_hvac_mode == HVACMode.OFF):
            self.sendPacket([0x00]) # switch off
        else:
            self.sendPacket([0x10]) # switch on

    def teach_in_actor(self) -> None:
        """Send teach-in telegram for temperature sensor."""
        self.sendPacket([0x40, 0x30, 0x02, 0x86])

    def teach_in_actor_switch(self) -> None:
        """Send teach-in telegram for switch sensor."""
        self.sendPacket([0x70])

    def sendPacket(self, data: list):
        """Compose and send packet."""
        if len(data) == 1:
            _LOGGER.debug(f"Send switch command packet for {self.dev_name}, value: {data[0]}")
            # packet type RPS
            command = [0xF6]
            command.extend(data)
            command.extend(self._sender_id_switch)
            command.extend([0x30])
            self.send_command(command, [], 0x01)    # button pressed
        else:
            _LOGGER.debug(f"Send temperature command packet for {self.dev_name}, setPoint: {data[1]}, temperature: {data[2]}")
            # packet type 4BS
            command = [0xA5]
            # 4 data bytes
            command.extend(data)
            # sender ID
            command.extend(self._sender_id)
            # Checksum byte
            command.extend([0x00])
            self.send_command(command, [], 0x01)