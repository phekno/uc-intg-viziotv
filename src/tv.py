"""
This module implements the Vizio SmartCast communication of the Remote Two integration driver.
"""

import asyncio
import logging
from asyncio import AbstractEventLoop
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, cast

import aiohttp
import wakeonlan
import config
from config import VizioConfigDevice
from pyee.asyncio import AsyncIOEventEmitter
from pyvizio import Vizio, VizioAsync, guess_device_type
from pyvizio.const import DEVICE_CLASS_TV
from ucapi.media_player import Attributes as MediaAttr

from const import EVENTS, PowerState, VIZIO_KEY_MAPPING

_LOG = logging.getLogger(__name__)

BACKOFF_MAX = 30
BACKOFF_SEC = 2


class VizioTv:
    """Representing a Vizio TV Device."""

    def __init__(
        self, device: VizioConfigDevice, loop: AbstractEventLoop | None = None
    ) -> None:
        """Create instance."""
        self._loop: AbstractEventLoop = loop or asyncio.get_running_loop()
        self.events = AsyncIOEventEmitter(self._loop)
        self._is_on: bool = False
        self._is_connected: bool = False
        self._vizio: Vizio | None = None
        self._device: VizioConfigDevice = device
        self._mac_address: str = device.mac_address if device.mac_address else ""
        self._connect_task = None
        self._connection_attempts: int = 0
        self._polling = None
        self._poll_interval: int = 10
        self._state: PowerState | None = None
        self._app_list: dict[str, str] = {}
        self._volume_level: float = 0.0
        self._end_of_power_off: datetime | None = None
        self._end_of_power_on: datetime | None = None
        self._active_source: str = ""
        self._power_on_task: asyncio.Task | None = None
        self._input_list: List[str] = []

    @property
    def device_config(self) -> VizioConfigDevice:
        """Return the device configuration."""
        return self._device

    @property
    def id(self) -> str:
        """Return the device identifier."""
        if not self._device.id:
            raise ValueError("Instance not initialized, no identifier available")
        return self._device.id

    @property
    def log_id(self) -> str:
        """Return a log identifier."""
        return self._device.name if self._device.name else self._device.id

    @property
    def name(self) -> str:
        """Return the device name."""
        return self._device.name

    @property
    def address(self) -> str | None:
        """Return the optional device address."""
        return self._device.address

    @property
    def is_on(self) -> bool | None:
        """Whether the Vizio TV is on or off. Returns None if not connected."""
        return self._is_on

    @property
    def state(self) -> PowerState | None:
        """Return the device state."""
        if self.is_on:
            return PowerState.ON
        return PowerState.OFF

    @property
    def is_connected(self) -> bool:
        """Return if the device is connected."""
        return self._vizio is not None and self._is_connected

    @property
    def source_list(self) -> list[str]:
        """Return a list of available input sources."""
        return sorted(self._input_list + list(self._app_list.keys()))

    @property
    def source(self) -> str:
        """Return the current input source."""
        return self._active_source

    @property
    def attributes(self) -> dict[str, any]:
        """Return the device attributes."""
        updated_data = {
            MediaAttr.STATE: self.state,
        }
        if self.source_list:
            updated_data[MediaAttr.SOURCE_LIST] = self.source_list
        if self.source:
            updated_data[MediaAttr.SOURCE] = self.source
        return updated_data

    @property
    def power_off_in_progress(self) -> bool:
        """Return if power off has been recently requested."""
        return (
            self._end_of_power_off is not None
            and self._end_of_power_off > datetime.utcnow()
        )

    @property
    def power_on_in_progress(self) -> bool:
        """Return if power on has been recently requested."""
        return (
            self._end_of_power_on is not None
            and self._end_of_power_on > datetime.utcnow()
        )

    def update_config(self, device: VizioConfigDevice) -> None:
        """Update the device configuration."""
        self._device = device
        self._mac_address = device.mac_address if device.mac_address else ""

    async def connect(self) -> None:
        """Establish connection to TV."""
        if self._vizio is not None and self._is_connected:
            return

        _LOG.debug("[%s] Connecting to device", self.log_id)
        if not self._connect_task:
            self.events.emit(EVENTS.CONNECTING, self._device.id)
            self._connect_task = asyncio.create_task(self._connect_setup())
        else:
            _LOG.debug(
                "[%s] Not starting connect setup (Vizio TV: %s, ConnectTask: %s)",
                self.log_id,
                self._vizio is not None,
                self._connect_task is not None,
            )

    async def _connect_setup(self) -> None:
        try:
            await self._connect()

            if self._vizio is not None and self._is_connected:
                _LOG.debug("[%s] Device is alive", self.log_id)
                self._is_on = True
                self.events.emit(
                    EVENTS.UPDATE, self._device.id, {"state": PowerState.ON}
                )
            else:
                _LOG.debug("[%s] Device is not alive", self.log_id)
                self.events.emit(
                    EVENTS.UPDATE, self._device.id, {"state": PowerState.OFF}
                )
                await self.disconnect()
        except asyncio.CancelledError:
            pass
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.error("[%s] Could not connect: %s", self.log_id, err)
            self._vizio = None
            self._is_connected = False
        finally:
            _LOG.debug("[%s] Connect setup finished", self.log_id)

        self.events.emit(EVENTS.CONNECTED, self._device.id)
        _LOG.debug("[%s] Connected", self.log_id)

        await asyncio.sleep(1)
        await self._start_polling()
        await self._update_input_list()
        await self._update_app_list()

    async def _connect(self) -> None:
        """Connect to the device."""
        _LOG.debug(
            "[%s] Connecting to Vizio device at IP address: %s",
            self.log_id,
            self._device.address,
        )
        
        device_type = DEVICE_CLASS_TV
        try:
            # Try to guess the device type
            device_type = guess_device_type(self._device.address)
        except Exception as err:
            _LOG.warning("[%s] Could not guess device type, using default: %s", self.log_id, err)
        
        self._vizio = Vizio(
            device_id=self._device.id,
            ip=self._device.address,
            name=self._device.name,
            auth_token=self._device.key,
            device_type=device_type,
            timeout=5
        )
        
        # Test connection
        try:
            power_state = self._vizio.get_power_state()
            self._is_connected = True
            self._is_on = power_state
            _LOG.debug("[%s] Connected to Vizio TV, power state: %s", self.log_id, power_state)
        except Exception as err:
            _LOG.error("[%s] Could not connect to Vizio TV: %s", self.log_id, err)
            self._is_connected = False
            self._vizio = None
            raise

    async def disconnect(self, continue_polling: bool = True) -> None:
        """Disconnect from Vizio."""
        _LOG.debug("[%s] Disconnecting from device", self.log_id)
        if not continue_polling:
            await self._stop_polling()

        try:
            if self._connect_task:
                _LOG.debug("[%s] Cancelling connect task", self.log_id)
                self._connect_task.cancel()
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.exception(
                "[%s] An error occurred while cancelling the connect task: %s",
                self.log_id,
                err,
            )
        finally:
            self._connect_task = None

        self._vizio = None
        self._is_connected = False
        _LOG.debug("[%s] Disconnected", self.log_id)
        self.events.emit(EVENTS.DISCONNECTED, self._device.id)

    async def _start_polling(self) -> None:
        if not self._polling:
            self._polling = self._loop.create_task(self._poll_worker())
            _LOG.debug("[%s] Polling started", self.log_id)

    async def _stop_polling(self) -> None:
        if self._polling:
            self._polling.cancel()
            self._polling = None
            _LOG.debug("[%s] Polling stopped", self.log_id)
        else:
            _LOG.debug("[%s] Polling was already stopped", self.log_id)

    async def check_connection_and_reconnect(self) -> None:
        """Check if the connection is alive and reconnect if not."""
        if self._vizio is None or not self._is_connected:
            _LOG.debug("[%s] Connection is not alive, reconnecting", self.log_id)
            await self.connect()
            return

    async def _update_input_list(self) -> None:
        """Update the list of available inputs."""
        _LOG.debug("[%s] Updating input list", self.log_id)
        update = {}

        try:
            if self._vizio and self._is_connected:
                inputs = self._vizio.get_inputs_list()
                if inputs:
                    self._input_list = [input_item.name for input_item in inputs]
                    update["source_list"] = self._input_list
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.exception("[%s] Input list: error: %s", self.log_id, err)

        if update:
            self.events.emit(EVENTS.UPDATE, self._device.id, update)

    async def _update_app_list(self) -> None:
        """Update the list of available apps."""
        _LOG.debug("[%s] Updating app list", self.log_id)
        update = {}

        try:
            if self._vizio and self._is_connected:
                apps = self._vizio.get_apps_list()
                if apps:
                    # Create a dictionary with app name as key and app name as value
                    # since we don't have app IDs in the same way as Samsung
                    self._app_list = {app: app for app in apps}
                    update["source_list"] = self.source_list
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.exception("[%s] App list: error: %s", self.log_id, err)

        if update:
            self.events.emit(EVENTS.UPDATE, self._device.id, update)

    async def _update_current_input(self) -> None:
        """Update the current input."""
        _LOG.debug("[%s] Updating current input", self.log_id)
        update = {}

        try:
            if self._vizio and self._is_connected:
                current_input = self._vizio.get_current_input()
                if current_input:
                    self._active_source = current_input
                    update["source"] = current_input
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.exception("[%s] Current input: error: %s", self.log_id, err)

        if update:
            self.events.emit(EVENTS.UPDATE, self._device.id, update)

    async def _update_current_app(self) -> None:
        """Update the current app."""
        _LOG.debug("[%s] Updating current app", self.log_id)
        update = {}

        try:
            if self._vizio and self._is_connected:
                current_app = self._vizio.get_current_app()
                if current_app and current_app != "Unknown App" and current_app != "No App Running":
                    self._active_source = current_app
                    update["source"] = current_app
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOG.exception("[%s] Current app: error: %s", self.log_id, err)

        if update:
            self.events.emit(EVENTS.UPDATE, self._device.id, update)

    async def launch_app(
        self, app_id: str | None = None, app_name: str | None = None
    ) -> None:
        """Launch an app on the TV."""
        if self.power_off_in_progress:
            _LOG.debug("TV is powering off, not sending launch_app command")
            return
        
        await self.check_connection_and_reconnect()
        
        if not self._vizio or not self._is_connected:
            _LOG.error("[%s] Cannot launch app, TV is not connected", self.log_id)
            return
            
        if app_name:
            if app_name.startswith("HDMI"):
                # Handle HDMI inputs
                try:
                    await self._vizio.set_input(app_name)
                    self._active_source = app_name
                    self.events.emit(EVENTS.UPDATE, self._device.id, {"source": app_name})
                except Exception as err:
                    _LOG.error("[%s] Error setting input to %s: %s", self.log_id, app_name, err)
            elif app_name in self._app_list:
                # Launch app by name
                try:
                    self._vizio.launch_app(app_name)
                    self._active_source = app_name
                    self.events.emit(EVENTS.UPDATE, self._device.id, {"source": app_name})
                except Exception as err:
                    _LOG.error("[%s] Error launching app %s: %s", self.log_id, app_name, err)

    async def send_key(self, key: str) -> None:
        """Send a key to the TV."""
        await self.check_connection_and_reconnect()
        
        if not self._vizio or not self._is_connected:
            _LOG.error(
                "[%s] Cannot send key '%s', TV is not connected",
                self.log_id,
                key,
            )
            return
            
        # Map the key to a Vizio remote key if possible
        vizio_key = VIZIO_KEY_MAPPING.get(key.replace("KEY_", ""), None)
        
        if vizio_key:
            try:
                self._vizio.remote(vizio_key)
            except Exception as err:
                _LOG.error("[%s] Error sending key %s: %s", self.log_id, vizio_key, err)
        else:
            _LOG.warning("[%s] No mapping for key: %s", self.log_id, key)

    async def _poll_worker(self) -> None:
        """Poll the TV for updates."""
        await asyncio.sleep(1)
        while True:
            try:
                if self._vizio and self._is_connected:
                    # Update power state
                    power_state = self._vizio.get_power_state()
                    if power_state != self._is_on:
                        self._is_on = power_state
                        state = PowerState.ON if power_state else PowerState.OFF
                        self.events.emit(EVENTS.UPDATE, self._device.id, {"state": state})
                    
                    # Only update other info if TV is on
                    if self._is_on:
                        # Update current input
                        await self._update_current_input()
                        # Update current app
                        await self._update_current_app()
                else:
                    # Try to reconnect if not connected
                    await self.connect()
            except Exception as err:
                _LOG.error("[%s] Error in poll worker: %s", self.log_id, err)
                
            await asyncio.sleep(self._poll_interval)

    async def toggle_power(self, power: bool | None = None) -> None:
        """Handle power state change."""
        update = {}
        if self.power_off_in_progress:
            _LOG.debug("TV is powering off, attempting to send power command")
            if self._vizio:
                self._vizio.pow_on()
            self._end_of_power_off = None
            self._power_on_task = asyncio.create_task(self.power_on())
            update["state"] = PowerState.ON
            self.events.emit(EVENTS.UPDATE, self._device.id, update)
            return

        if self.power_on_in_progress:
            _LOG.debug("TV is powering on, not sending power command")
            return

        if power is None:
            power = not self._is_on

        if power:
            if self._vizio is not None and self._is_connected and self._is_on:
                update["state"] = PowerState.ON
            else:
                self._end_of_power_on = datetime.utcnow() + timedelta(seconds=15)
                self._power_on_task = asyncio.create_task(self.power_on())
            self._is_on = True
        else:
            if self._vizio and self._is_connected:
                try:
                    self._vizio.pow_off()
                except Exception as err:
                    _LOG.error("[%s] Error powering off: %s", self.log_id, err)
            self._end_of_power_off = datetime.utcnow() + timedelta(seconds=65)
            self._is_on = False
            update["state"] = PowerState.OFF

        self.events.emit(EVENTS.UPDATE, self._device.id, update)

    async def power_on(self) -> None:
        """Power on the TV."""
        update = {}
        
        # First try using the Vizio API
        if self._vizio:
            try:
                self._vizio.pow_on()
                self._is_on = True
                update["state"] = PowerState.ON
                self.events.emit(EVENTS.UPDATE, self._device.id, update)
                return
            except Exception as err:
                _LOG.warning("[%s] Could not power on using API: %s", self.log_id, err)
        
        # If that fails, try Wake-on-LAN
        if self._device.mac_address:
            for i in range(7):
                _LOG.debug("[%s] Sending magic packet (%s)", self.log_id, i)
                try:
                    # Send to both MAC addresses if available
                    wakeonlan.send_magic_packet(self._device.mac_address)
                    if self._device.mac_address2:
                        wakeonlan.send_magic_packet(self._device.mac_address2)
                except Exception as err:
                    _LOG.error("[%s] Error sending magic packet: %s", self.log_id, err)
                
                await asyncio.sleep(2)
                
                # Check if TV is on
                if self._vizio:
                    try:
                        power_state = self._vizio.get_power_state()
                        if power_state:
                            self._is_on = True
                            update["state"] = PowerState.ON
                            break
                    except Exception:
                        pass
                
                # Try to reconnect
                await self.check_connection_and_reconnect()
                
                if self._is_on:
                    update["state"] = PowerState.ON
                    break

        if not self._is_on:
            _LOG.warning("[%s] Unable to wake TV", self.log_id)
            update["state"] = PowerState.OFF

        self.events.emit(EVENTS.UPDATE, self._device.id, update)

    def wakeonlan(self) -> None:
        """Send Wake-on-LAN packet to the TV."""
        if self._device.mac_address:
            try:
                _LOG.debug("[%s] Sending magic packet to %s", self.log_id, self._device.mac_address)
                wakeonlan.send_magic_packet(self._device.mac_address)
            except Exception as err:
                _LOG.error("[%s] Error sending magic packet: %s", self.log_id, err)
                
        if self._device.mac_address2:
            try:
                _LOG.debug("[%s] Sending magic packet to %s", self.log_id, self._device.mac_address2)
                wakeonlan.send_magic_packet(self._device.mac_address2)
            except Exception as err:
                _LOG.error("[%s] Error sending magic packet: %s", self.log_id, err)

    def get_device_info(self) -> dict[str, Any]:
        """Get device info from the TV."""
        info = {}
        
        if not self._vizio or not self._is_connected:
            return info
            
        try:
            info["ModelName"] = self._vizio.get_model_name()
        except Exception:
            pass
            
        try:
            info["SerialNumber"] = self._vizio.get_serial_number()
        except Exception:
            pass
            
        try:
            info["Version"] = self._vizio.get_version()
        except Exception:
            pass
            
        try:
            info["PowerState"] = "on" if self._vizio.get_power_state() else "off"
        except Exception:
            pass
            
        return info