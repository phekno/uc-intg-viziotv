#!/usr/bin/env python3
"""This module implements a discovery function for Vizio TV."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from pyvizio import Vizio, guess_device_type
from pyvizio.const import DEVICE_CLASS_TV
from pyvizio.discovery.zeroconf import ZeroconfListener

_LOGGER = logging.getLogger(__name__)

# Thread pool for running synchronous pyvizio discovery calls
# without blocking the async event loop.
_executor = ThreadPoolExecutor(max_workers=2)


def _update_service(self, zeroconf, type, name):
    pass


ZeroconfListener.update_service = _update_service


def _discover_ssdp() -> list[dict]:
    """Run SSDP discovery synchronously (called in a thread)."""
    devices = []
    try:
        _LOGGER.debug("Starting SSDP discovery")
        ssdp_devices = Vizio.discovery_ssdp(timeout=10)
        _LOGGER.debug("SSDP discovery found %d devices", len(ssdp_devices))

        for device in ssdp_devices:
            try:
                ip = device.ip
                _LOGGER.debug("Processing SSDP device with IP: %s", ip)
                device_type = guess_device_type(ip)

                if device_type == DEVICE_CLASS_TV:
                    vizio = Vizio(
                        device_id="discovery",
                        ip=ip,
                        name="Temporary",
                        device_type=device_type,
                    )
                    model_name = vizio.get_model_name() or "Unknown Model"
                    device_info = {
                        "host": ip,
                        "modelName": model_name,
                        "friendlyName": model_name,
                        "serialNumber": vizio.get_serial_number() or "",
                        "id": ip,
                    }
                    devices.append(device_info)
                    _LOGGER.info("Found Vizio TV via SSDP: %s", device_info)
            except Exception as ex:
                _LOGGER.error("Error processing SSDP device %s: %s", device.ip, ex)
    except Exception as ex:
        _LOGGER.error("Error during SSDP discovery: %s", ex)
    return devices


def _discover_zeroconf() -> list[dict]:
    """Run Zeroconf discovery synchronously (called in a thread)."""
    devices = []
    try:
        _LOGGER.debug("Starting Zeroconf discovery")
        zeroconf_devices = Vizio.discovery_zeroconf(timeout=10)
        _LOGGER.debug("Zeroconf discovery found %d devices", len(zeroconf_devices))

        for device in zeroconf_devices:
            try:
                ip = device.ip
                _LOGGER.debug("Processing Zeroconf device with IP: %s", ip)
                device_type = guess_device_type(ip)

                if device_type == DEVICE_CLASS_TV:
                    vizio = Vizio(
                        device_id="discovery",
                        ip=ip,
                        name="Temporary",
                        device_type=device_type,
                    )
                    model_name = vizio.get_model_name() or "Unknown Model"
                    device_info = {
                        "host": ip,
                        "modelName": model_name,
                        "friendlyName": device.name or model_name,
                        "serialNumber": vizio.get_serial_number() or "",
                        "id": device.model or ip,
                    }
                    devices.append(device_info)
                    _LOGGER.info("Found Vizio TV via Zeroconf: %s", device_info)
            except Exception as ex:
                _LOGGER.error("Error processing Zeroconf device %s: %s", device.ip, ex)
    except Exception as ex:
        _LOGGER.error("Error during Zeroconf discovery: %s", ex)
    return devices


def _discover_all() -> list[dict]:
    """Run both SSDP and Zeroconf discovery synchronously (called in a thread)."""
    ssdp_devices = _discover_ssdp()
    zeroconf_devices = _discover_zeroconf()

    # Merge and deduplicate by host
    unique_devices: dict[str, dict] = {}
    for device in ssdp_devices + zeroconf_devices:
        host = device.get("host")
        if host and host not in unique_devices:
            unique_devices[host] = device

    return list(unique_devices.values())


async def async_identify_vizio_devices() -> list[dict]:
    """
    Identify Vizio TVs using pyvizio discovery.

    Runs the synchronous pyvizio discovery in a thread executor
    so it doesn't block the async event loop.

    Returns a list of dictionaries with discovered Vizio devices.
    """
    _LOGGER.info("Starting Vizio TV discovery process")
    loop = asyncio.get_event_loop()
    devices = await loop.run_in_executor(_executor, _discover_all)
    _LOGGER.info("Discovery complete, found %d device(s)", len(devices))
    return devices
