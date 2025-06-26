#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""This module implements a discovery function for Vizio TV."""

import asyncio
import logging
import socket
import sys
from typing import Dict, List, Optional, Set

import pyvizio
from pyvizio import Vizio, guess_device_type
from pyvizio.const import DEVICE_CLASS_TV

_LOGGER = logging.getLogger(__name__)


async def async_identify_vizio_devices() -> List[Dict]:
    """
    Identify Vizio TVs using pyvizio discovery.

    Returns a list of dictionaries which includes all discovered Vizio
    devices with keys "host", "modelName", "friendlyName", etc.
    """
    # Discover Vizio devices using both SSDP and Zeroconf
    devices = []
    
    # Use SSDP discovery
    try:
        ssdp_devices = Vizio.discovery_ssdp()
        _LOGGER.debug("SSDP discovery found %d devices", len(ssdp_devices))
        
        for device in ssdp_devices:
            try:
                ip = device.ip
                device_type = guess_device_type(ip)
                
                # Only include TV devices
                if device_type == DEVICE_CLASS_TV:
                    # Get a unique ID for the device
                    unique_id = await pyvizio.get_unique_id(ip, device_type)
                    
                    # Create a temporary Vizio instance to get device info
                    vizio = Vizio(
                        device_id=unique_id or "unknown",
                        ip=ip,
                        name="Temporary",
                        device_type=device_type
                    )
                    
                    # Get device information
                    model_name = vizio.get_model_name() or "Unknown Model"
                    friendly_name = model_name
                    
                    # Create device info dictionary
                    device_info = {
                        "host": ip,
                        "modelName": model_name,
                        "friendlyName": friendly_name,
                        "serialNumber": vizio.get_serial_number() or "",
                        "id": unique_id or "",
                    }
                    
                    devices.append(device_info)
                    _LOGGER.debug("Found Vizio TV: %s", device_info)
            except Exception as ex:
                _LOGGER.error("Error processing SSDP device %s: %s", device.ip, ex)
    except Exception as ex:
        _LOGGER.error("Error during SSDP discovery: %s", ex)
    
    # Use Zeroconf discovery
    try:
        zeroconf_devices = Vizio.discovery_zeroconf()
        _LOGGER.debug("Zeroconf discovery found %d devices", len(zeroconf_devices))
        
        for device in zeroconf_devices:
            try:
                ip = device.ip
                device_type = guess_device_type(ip)
                
                # Only include TV devices
                if device_type == DEVICE_CLASS_TV:
                    # Check if we already found this device via SSDP
                    if any(d["host"] == ip for d in devices):
                        continue
                        
                    # Get a unique ID for the device
                    unique_id = await pyvizio.get_unique_id(ip, device_type)
                    
                    # Create a temporary Vizio instance to get device info
                    vizio = Vizio(
                        device_id=unique_id or "unknown",
                        ip=ip,
                        name="Temporary",
                        device_type=device_type
                    )
                    
                    # Get device information
                    model_name = vizio.get_model_name() or "Unknown Model"
                    friendly_name = model_name
                    
                    # Create device info dictionary
                    device_info = {
                        "host": ip,
                        "modelName": model_name,
                        "friendlyName": friendly_name,
                        "serialNumber": vizio.get_serial_number() or "",
                        "id": unique_id or "",
                    }
                    
                    devices.append(device_info)
                    _LOGGER.debug("Found Vizio TV: %s", device_info)
            except Exception as ex:
                _LOGGER.error("Error processing Zeroconf device %s: %s", device.ip, ex)
    except Exception as ex:
        _LOGGER.error("Error during Zeroconf discovery: %s", ex)
    
    # Deduplicate devices by host
    unique_devices: dict[str, dict[str, any]] = {}
    for device in devices:
        unique_devices[device.get("host")] = device

    return list(unique_devices.values())


def get_local_ips() -> List[str]:
    """Get IPs of local network adapters."""
    return [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None)]