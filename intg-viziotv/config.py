"""
Configuration handling of the integration driver.

:copyright: (c) 2023 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import dataclasses
import json
import logging
import os
from dataclasses import dataclass
from typing import Iterator

from asyncio import Lock

from ucapi import EntityTypes

_LOG = logging.getLogger(__name__)

_CFG_FILENAME = "config.json"


def create_entity_id(device_id: str, entity_type: EntityTypes) -> str:
    """Create a unique entity identifier for the given receiver and entity type."""
    return f"{entity_type.value}.{device_id}"


def device_from_entity_id(entity_id: str) -> str | None:
    """
    Return the device_id prefix of an entity_id.

    The prefix is the part before the first dot in the name and refers to the device identifier.

    :param entity_id: the entity identifier
    :return: the device prefix, or None if entity_id doesn't contain a dot
    """
    try:
        return entity_id.split(".", 1)[1]
    except (IndexError, AttributeError):
        _LOG.warning("Invalid entity_id format: %s", entity_id)
        return None


@dataclass
class VizioDevice:
    
    id: str
    """Unique identifier of the device"""
    name: str
    """Unique name of the device"""
    address: str
    """IP address and port of the device"""
    auth_token: str = ""
    """Auth token for the device"""
    key: str = ""
    """Authentication key for the device"""
    mac_address: str = None
    """MAC address (wired) for Wake-on-LAN"""
    mac_address2: str = None
    """MAC address (wifi) for Wake-on-LAN"""
    interface: str = "0.0.0.0"
    """Interface to use for magic packet"""
    broadcast: str = None
    """Broadcast address to use for magic packet"""
    wol_port: int = 9
    """Wake on LAN port"""

class _EnhancedJSONEncoder(json.JSONEncoder):
    """Python dataclass json encoder."""

    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)


class Devices:
    """Integration driver configuration class. Manages all configured devices."""

    def __init__(self, data_path: str, add_handler, remove_handler):
        """
        Create a configuration instance for the given configuration path.

        :param data_path: configuration path for the configuration file and client device certificates.
        """
        self._data_path: str = data_path
        self._cfg_file_path: str = os.path.join(data_path, _CFG_FILENAME)
        self._config: list[VizioDevice] = []
        self._add_handler = add_handler
        self._remove_handler = remove_handler
        self.load()
        self._config_lock = Lock()

    @property
    def data_path(self) -> str:
        """Return the configuration path."""
        return self._data_path

    def all(self) -> Iterator[VizioDevice]:
        """Get an iterator for all device configurations."""
        _LOG.debug("in config.all")
        _LOG.debug(self._config)
        return iter(self._config)

    def contains(self, avr_id: str) -> bool:
        """Check if there's a device with the given device identifier."""
        for item in self._config:
            if item.id == avr_id:
                return True
        return False

    def add_or_update(self, tv: VizioDevice) -> None:
        """Add a new configured device."""
        if self.contains(tv.id):
            _LOG.debug("Existing config %s, updating it %s", tv.id, tv)
            self.update(tv)
        else:
            _LOG.debug("Adding new config %s", tv)
            self._config.append(tv)
            self.store()
        if self._add_handler is not None:
            self._add_handler(tv)

    def get(self, avr_id: str) -> VizioDevice | None:
        """Get device configuration for given identifier."""
        for item in self._config:
            if item.id == avr_id:
                # return a copy
                return dataclasses.replace(item)
        return None

    def update(self, device: VizioDevice) -> bool:
        """Update a configured device and persist configuration."""
        for item in self._config:
            if item.id == device.id:
                item.address = device.address
                item.name = device.name
                item.key = device.key
                item.mac_address = device.mac_address
                item.mac_address2 = device.mac_address2
                item.broadcast = device.broadcast
                item.interface = device.interface
                item.wol_port = device.wol_port
                return self.store()
        return False

    def remove(self, avr_id: str) -> bool:
        """Remove the given device configuration."""
        device = self.get(avr_id)
        if device is None:
            return False
        try:
            self._config.remove(device)
            if self._remove_handler is not None:
                self._remove_handler(device)
            return True
        except ValueError:
            pass
        return False

    def clear(self) -> None:
        """Remove the configuration file."""
        self._config = []

        if os.path.exists(self._cfg_file_path):
            os.remove(self._cfg_file_path)

        if self._remove_handler is not None:
            self._remove_handler(None)

    def store(self) -> bool:
        """
        Store the configuration file.

        :return: True if the configuration could be saved.
        """
        try:
            with open(self._cfg_file_path, "w+", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, cls=_EnhancedJSONEncoder)
            return True
        except OSError:
            _LOG.error("Cannot write the config file")

        return False

    def load(self) -> bool:
        """
        Load the config into the config global variable.

        :return: True if the configuration could be loaded.
        """
        try:
            with open(self._cfg_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                try:
                    self._config.append(VizioDevice(**item))
                except TypeError as ex:
                    _LOG.warning("Invalid configuration entry will be ignored: %s", ex)
            return True
        except OSError:
            _LOG.error("Cannot open the config file")
        except ValueError:
            _LOG.error("Empty or invalid config file")

        return False


devices: Devices | None = None