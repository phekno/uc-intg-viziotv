"""
Setup flow for Vizio TV integration.

:copyright: (c) 2023 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import asyncio
import functools
import ipaddress
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from enum import IntEnum

import config
import discover
import pyvizio
import tv
from ucapi import (
    AbortDriverSetup,
    DriverSetupRequest,
    IntegrationSetupError,
    RequestUserInput,
    SetupAction,
    SetupComplete,
    SetupDriver,
    SetupError,
    UserDataResponse, 
    RequestUserConfirmation, 
    UserConfirmationResponse,
)

_LOG = logging.getLogger(__name__)

# Thread pool for running synchronous pyvizio calls that internally use
# asyncio.run(), which cannot be called from within a running event loop.
_executor = ThreadPoolExecutor(max_workers=1)


# pylint: disable = W1405


class SetupSteps(IntEnum):
    """Enumeration of setup steps to keep track of user data responses."""

    INIT = 0
    CONFIGURATION_MODE = 1
    DISCOVER = 2
    DEVICE_CHOICE = 3
    PAIRING = 4
    ADDITIONAL_SETTINGS = 5
    TEST_WAKEONLAN = 6


_setup_step = SetupSteps.INIT
_cfg_add_device: bool = False
_discovered_devices: list[dict[str, str]] = []
_pairing_vizio_tv = None
_config_device = None
_user_input_discovery = RequestUserInput(
    {"en": "Setup mode",},
    [
        {
            "id": "info",
            "label": {
                "en": "Discover or connect to Vizio devices",
            },
            "field": {
                "label": {
                    "value": {
                        "en": "Leave blank to use auto-discovery.",
                    }
                }
            },
        },
        {
            "field": {"text": {"value": ""}},
            "id": "address",
            "label": {"en": "IP address",},
        },
    ],
)

_pairing_challenge_type = None
_pairing_req_token = None


async def driver_setup_handler(
    msg: SetupDriver,
) -> SetupAction:  # pylint: disable=too-many-return-statements
    """
    Dispatch driver setup requests to corresponding handlers.

    Either start the setup process or handle the selected Vizio TV device.

    :param msg: the setup driver request object, either DriverSetupRequest or UserDataResponse
    :return: the setup action on how to continue
    """
    try:
        if isinstance(msg, DriverSetupRequest):
            return await handle_driver_setup(msg)
        if isinstance(msg, UserDataResponse):
            return await handle_user_data_response(msg)
        else:
            _LOG.debug("Unknown message type: %s", type(msg))
        return SetupError()
    except StopIteration as ex:
        _LOG.error("StopIteration exception in setup handler: %s", ex)
        return SetupError(error_type=IntegrationSetupError.OTHER)
    except Exception as ex:
        _LOG.error("Exception in setup handler: %s", ex)
        return SetupError(error_type=IntegrationSetupError.OTHER)


async def handle_driver_setup(msg: DriverSetupRequest) -> RequestUserInput | SetupError:
    """
    Start driver setup.

    Initiated by Remote Two to set up the driver.
    Ask user to enter ip-address for manual configuration, otherwise auto-discovery is used.

    :param msg: not used, we don't have any input fields in the first setup screen.
    :return: the setup action on how to continue
    """
    try:
        await asyncio.sleep(1)

        if msg.reconfigure:
            _LOG.debug("Ignoring driver reconfiguration request")
        
        # If we have configured devices, show configuration mode
        devices_list = list(config.devices.all())
        if devices_list:
            _setup_step = SetupSteps.CONFIGURATION_MODE
            _LOG.debug("Found %d configured device(s)", len(devices_list))
            
            # Create options for device selection
            device_options = []
            default_device_id = ""
            
            try:
                for device in devices_list:
                    device_options.append({
                        "id": device.id,
                        "label": {"en": f"{device.name} ({device.address})"},
                    })
                    if not default_device_id:
                        default_device_id = device.id
            except Exception as ex:
                _LOG.error("Error processing device list: %s", ex)
                
            return RequestUserInput(
                title={"en": "Configuration mode"},
                settings=[
                    {
                        "id": "info",
                        "label": {"en": "Configuration mode"},
                        "field": {
                            "label": {
                                "value": {
                                    "en": "Choose configuration mode",
                                }
                            }
                        },
                    },
                    {
                        "id": "action",
                        "label": {"en": "Action"},
                        "field": {
                            "dropdown": {
                                "value": "add",
                                "items": [
                                    {"id": "add", "label": {"en": "Add new Vizio TV"}},
                                    {"id": "remove", "label": {"en": "Remove Vizio TV"}},
                                    {"id": "configure", "label": {"en": "Configure existing Vizio TV"}},
                                    {"id": "reset", "label": {"en": "Reset configuration"}},
                                ],
                            }
                        },
                    },
                ]
                + (
                    [
                        {
                            "id": "choice",
                            "label": {"en": "Device"},
                            "field": {
                                "dropdown": {
                                    "value": default_device_id,
                                    "items": device_options,
                                }
                            },
                        }
                    ]
                    if device_options
                    else []
                ),
            )

        # No configured devices, go straight to discovery
        _LOG.info("No devices configured yet. Going to discovery step.")
        _setup_step = SetupSteps.DISCOVER
        return _user_input_discovery
    except StopIteration as ex:
        _LOG.error("StopIteration exception in handle_driver_setup: %s", ex)
        return SetupError(error_type=IntegrationSetupError.OTHER)
    except Exception as ex:
        _LOG.error("Exception in handle_driver_setup: %s", ex)
        return SetupError(error_type=IntegrationSetupError.OTHER)


async def handle_user_data_response(msg: UserDataResponse) -> SetupAction:
    """
    Process user data response in a setup process.

    Driver setup callback to provide requested user data during the setup process.

    :param msg: response data from the requested user data
    :return: the setup action on how to continue
    """
    global _setup_step

    _LOG.debug("Processing user data response for step: %s", _setup_step)

    # If we're in INIT state, move to DISCOVER
    if _setup_step == SetupSteps.INIT:
        _LOG.debug("Moving from INIT to DISCOVER step")
        _setup_step = SetupSteps.DISCOVER
        return await handle_discovery(msg)

    match _setup_step:
        case SetupSteps.CONFIGURATION_MODE:
            return await handle_configuration_mode(msg)
        case SetupSteps.DISCOVER:
            return await handle_discovery(msg)
        case SetupSteps.DEVICE_CHOICE:
            return await handle_device_choice(msg)
        case SetupSteps.PAIRING:
            return await handle_pairing(msg)
        case SetupSteps.ADDITIONAL_SETTINGS:
            return await handle_additional_settings(msg)
        case SetupSteps.TEST_WAKEONLAN:
            return await handle_wake_on_lan(msg)
        case _:
            _LOG.error("Invalid setup step: %s", _setup_step)
            return SetupError(error_type=IntegrationSetupError.OTHER)


async def handle_user_confirmation_response(msg: UserConfirmationResponse) -> SetupAction:
    """
    Process user confirmation response in a setup process.

    :param msg: response data from the requested user confirmation
    :return: the setup action on how to continue
    """
    global _setup_step

    if _setup_step == SetupSteps.TEST_WAKEONLAN:
        if msg.confirmed:
            return get_wakeonlan_settings()
        return SetupComplete()

    return SetupError(error_type=IntegrationSetupError.OTHER)


async def handle_configuration_mode(msg: UserDataResponse) -> RequestUserInput | SetupComplete | SetupError:
    """
    Process user data response in a setup process.

    If ``address`` field is set by the user: try connecting to device and retrieve model information.
    Otherwise, start Vizio TV discovery and present the found devices to the user to choose from.

    :param msg: response data from the requested user data
    :return: the setup action on how to continue
    """
    global _setup_step
    global _cfg_add_device
    global _config_device

    action = msg.input_values["action"]

    # workaround for web-configurator not picking up first response
    await asyncio.sleep(1)

    match action:
        case "add":
            _cfg_add_device = True
        case "remove":
            choice = msg.input_values["choice"]
            if not config.devices.remove(choice):
                _LOG.warning("Could not remove device from configuration: %s", choice)
                return SetupError(error_type=IntegrationSetupError.OTHER)
            config.devices.store()
            return SetupComplete()
        case "configure":
            choice = msg.input_values["choice"]
            if not config.devices.contains(choice):
                _LOG.warning("Could not configure existing device from configuration: %s", choice)
                return SetupError(error_type=IntegrationSetupError.OTHER)
            _config_device = config.devices.get(choice)
            return get_additional_settings(_config_device)
        case "reset":
            config.devices.clear()  # triggers device instance removal
        case _:
            _LOG.error("Invalid configuration action: %s", action)
            return SetupError(error_type=IntegrationSetupError.OTHER)

    _setup_step = SetupSteps.DISCOVER
    return _user_input_discovery


async def handle_discovery(msg: UserDataResponse) -> RequestUserInput | SetupError:
    """
    Process user data response in a setup process.

    If ``address`` field is set by the user: try connecting to device and retrieve model information.
    Otherwise, start Vizio TV discovery and present the found devices to the user to choose from.

    :param msg: response data from the requested user data
    :return: the setup action on how to continue
    """
    global _setup_step
    global _discovered_devices

    try:
        # Initialize _discovered_devices to empty list if it's None
        if _discovered_devices is None:
            _discovered_devices = []
            
        # Get address from msg if available, otherwise use empty string
        address = ""
        if msg and hasattr(msg, 'input_values'):
            address = msg.input_values.get("address", "")
        
        _LOG.info("Handle discovery with address: '%s'", address)

        # workaround for web-configurator not picking up first response
        await asyncio.sleep(1)

        if address:
            # Manual configuration: try to connect to the given address
            _LOG.info("Attempting manual configuration with address: %s", address)
            try:
                # Check if we can connect to the device
                _LOG.debug("Guessing device type for %s", address)
                loop = asyncio.get_event_loop()
                device_type = await loop.run_in_executor(_executor, functools.partial(pyvizio.guess_device_type, address))
                _LOG.debug("Device type for %s: %s", address, device_type)
                
                if device_type != pyvizio.DEVICE_CLASS_TV:
                    _LOG.warning("Device at %s is not a Vizio TV (type: %s)", address, device_type)
                    # Show manual IP entry dialog again with error message
                    return RequestUserInput(
                        title={"en": "Device Not a Vizio TV"},
                        settings=[
                            {
                                "id": "info",
                                "label": {"en": "Device Not a Vizio TV"},
                                "field": {
                                    "label": {
                                        "value": {
                                            "en": f"The device at {address} is not a Vizio TV. Please enter a valid Vizio TV IP address.",
                                        }
                                    }
                                },
                            },
                            {
                                "field": {"text": {"value": ""}},
                                "id": "address",
                                "label": {"en": "IP address"},
                            },
                        ],
                    )
                
                # Create a device entry
                _LOG.debug("Creating manual device entry for %s", address)
                _discovered_devices = [{"host": address, "modelName": "Vizio TV", "friendlyName": "Vizio TV"}]
                _LOG.debug("Manual device entry created: %s", _discovered_devices)
                
            except Exception as ex:
                _LOG.error("Cannot connect to %s: %s", address, ex)
                # Show manual IP entry dialog again with error message
                return RequestUserInput(
                    title={"en": "Connection Error"},
                    settings=[
                        {
                            "id": "info",
                            "label": {"en": "Connection Error"},
                            "field": {
                                "label": {
                                    "value": {
                                        "en": f"Could not connect to {address}: {ex}. Please enter a valid Vizio TV IP address.",
                                    }
                                }
                            },
                        },
                        {
                            "field": {"text": {"value": ""}},
                            "id": "address",
                            "label": {"en": "IP address"},
                        },
                    ],
                )
        else:
            # Auto-discovery: find Vizio TVs on the network
            _LOG.info("Starting auto-discovery of Vizio TVs")
            try:
                # Clear any previous discoveries
                _discovered_devices = []
                
                # Call the discovery function with a timeout
                _LOG.debug("Calling async_identify_vizio_devices")
                try:
                    # Create a task with a timeout
                    discovery_task = asyncio.create_task(discover.async_identify_vizio_devices())
                    _discovered_devices = await asyncio.wait_for(discovery_task, timeout=60.0)  # Increased timeout
                    _LOG.info("Discovery completed, found %d devices", len(_discovered_devices))
                except asyncio.TimeoutError:
                    _LOG.warning("Discovery timed out after 60 seconds")
                    # Show manual IP entry dialog
                    return RequestUserInput(
                        title={"en": "Discovery Timeout"},
                        settings=[
                            {
                                "id": "info",
                                "label": {"en": "Discovery Timeout"},
                                "field": {
                                    "label": {
                                        "value": {
                                            "en": "Discovery timed out. Please enter the IP address of your Vizio TV manually.",
                                        }
                                    }
                                },
                            },
                            {
                                "field": {"text": {"value": ""}},
                                "id": "address",
                                "label": {"en": "IP address"},
                            },
                        ],
                    )
                
                # Validate the discovered devices
                if not _discovered_devices:
                    _LOG.warning("No Vizio TVs found on the network")
                    # Show manual IP entry dialog
                    return RequestUserInput(
                        title={"en": "No Vizio TVs Found"},
                        settings=[
                            {
                                "id": "info",
                                "label": {"en": "No Vizio TVs Found"},
                                "field": {
                                    "label": {
                                        "value": {
                                            "en": "No Vizio TVs were found on your network. Please enter the IP address manually.",
                                        }
                                    }
                                },
                            },
                            {
                                "field": {"text": {"value": ""}},
                                "id": "address",
                                "label": {"en": "IP address"},
                            },
                        ],
                    )
                
                # Log the discovered devices
                for i, device in enumerate(_discovered_devices):
                    _LOG.debug("Discovered device %d: %s", i, device)
            except Exception as ex:
                _LOG.error("Error during Vizio TV discovery: %s", ex)
                # Show manual IP entry dialog
                return RequestUserInput(
                    title={"en": "Discovery Error"},
                    settings=[
                        {
                            "id": "info",
                            "label": {"en": "Discovery Error"},
                            "field": {
                                "label": {
                                    "value": {
                                        "en": f"An error occurred during discovery: {ex}. Please enter the IP address manually.",
                                    }
                                }
                            },
                        },
                        {
                            "field": {"text": {"value": ""}},
                            "id": "address",
                            "label": {"en": "IP address"},
                        },
                    ],
                )

        # Ensure we have valid discovered devices
        if not _discovered_devices or len(_discovered_devices) == 0:
            _LOG.error("No devices discovered or discovery failed")
            # Show manual IP entry dialog
            return RequestUserInput(
                title={"en": "No Vizio TVs Found"},
                settings=[
                    {
                        "id": "info",
                        "label": {"en": "No Vizio TVs Found"},
                        "field": {
                            "label": {
                                "value": {
                                    "en": "No Vizio TVs were found on your network. Please enter the IP address manually.",
                                }
                            }
                        },
                    },
                    {
                        "field": {"text": {"value": ""}},
                        "id": "address",
                        "label": {"en": "IP address"},
                    },
                ],
            )
            
        # Create a safe default value for the select field
        default_device = _discovered_devices[0]["host"] if _discovered_devices else ""
        _LOG.debug("Default device for selection: %s", default_device)
        
        # Create options for the select field
        device_options = []
        try:
            for device in _discovered_devices:
                friendly_name = device.get("friendlyName", device.get("modelName", "Vizio TV"))
                host = device.get("host", "")
                if not host:
                    _LOG.warning("Skipping device with no host: %s", device)
                    continue
                    
                device_options.append({
                    "id": host,
                    "label": {"en": f"{friendly_name} ({host})"},
                })
        except Exception as ex:
            _LOG.error("Error creating device options: %s", ex)
            return SetupError(error_type=IntegrationSetupError.OTHER)
            
        if not device_options:
            _LOG.error("No valid device options created")
            return SetupError(error_type=IntegrationSetupError.DEVICE_NOT_FOUND)
            
        _LOG.debug("Created %d device options", len(device_options))

        # Present the discovered devices to the user
        _setup_step = SetupSteps.DEVICE_CHOICE
        _LOG.debug("Moving to DEVICE_CHOICE step")
        return RequestUserInput(
            title={"en": "Select Vizio TV"},
            settings=[
                {
                    "id": "info",
                    "label": {"en": "Select Vizio TV"},
                    "field": {
                        "label": {
                            "value": {
                                "en": "Select the Vizio TV to configure",
                            }
                        }
                    },
                },
                {
                    "id": "choice",
                    "label": {"en": "Device"},
                    "field": {
                        "dropdown": {
                            "value": default_device,
                            "items": device_options,
                        }
                    },
                },
            ],
        )
    except StopIteration as ex:
        _LOG.error("StopIteration exception in handle_discovery: %s", ex)
        return SetupError(error_type=IntegrationSetupError.OTHER)
    except Exception as ex:
        _LOG.error("Exception in handle_discovery: %s", ex)
        return SetupError(error_type=IntegrationSetupError.OTHER)


async def handle_device_choice(msg: UserDataResponse) -> RequestUserInput | SetupError:
    """
    Process user data response in a setup process.

    Driver setup callback to provide requested user data during the setup process.

    :param msg: response data from the requested user data
    :return: the setup action on how to continue
    """
    global _discovered_devices
    global _pairing_vizio_tv
    global _config_device
    global _setup_step
    
    try:
        _LOG.debug("Handling device choice")
        
        # Initialize variables
        discovered_device = None
        host = msg.input_values.get("choice", "")
        
        _LOG.debug("User selected device with host: '%s'", host)
        
        if not host:
            _LOG.error("No device selected")
            return SetupError(error_type=IntegrationSetupError.OTHER)
            
        mac_address = None
        mac_address2 = None

        # Find the selected device in the discovered devices list
        if _discovered_devices:
            _LOG.debug("Searching for selected device in %d discovered devices", len(_discovered_devices))
            for device in _discovered_devices:
                device_host = device.get("host", None)
                _LOG.debug("Checking device with host: %s", device_host)
                if device_host == host:
                    _LOG.debug("Found matching device: %s", device)
                    discovered_device = device
                    if device.get("wiredMac"):
                        mac_address = device.get("wiredMac")
                        _LOG.debug("Found wired MAC: %s", mac_address)
                    if device.get("wifiMac"):
                        mac_address2 = device.get("wifiMac")
                        _LOG.debug("Found WiFi MAC: %s", mac_address2)
                    break

        # If the device wasn't found, create a default one
        if not discovered_device:
            _LOG.warning("Selected device not found in discovered devices list, creating default device")
            discovered_device = {"host": host, "modelName": "Vizio TV", "friendlyName": "Vizio TV"}

        _LOG.debug("Chosen Vizio TV: %s (wired mac %s, wifi mac %s). Trying to connect and retrieve device information...",
                host, mac_address, mac_address2)
        
        try:
            # Get a unique ID for the device
            _LOG.debug("Getting unique ID for device at %s", host)
            try:
                # Use a timeout to prevent hanging
                unique_id_task = asyncio.create_task(pyvizio.VizioAsync.get_unique_id(host, pyvizio.DEVICE_CLASS_TV))
                unique_id = await asyncio.wait_for(unique_id_task, timeout=10.0)
                _LOG.debug("Got unique ID: %s", unique_id)
            except asyncio.TimeoutError:
                _LOG.error("Timeout getting unique ID for Vizio TV at %s", host)
                return SetupError(error_type=IntegrationSetupError.TIMEOUT)
                
            if not unique_id:
                _LOG.error("Could not get unique ID for Vizio TV at %s", host)
                return SetupError(error_type=IntegrationSetupError.OTHER)
            
            # Create a Vizio device instance
            _LOG.debug("Creating Vizio device instance")
            try:
                device_name = discovered_device.get("friendlyName", discovered_device.get("modelName", "Vizio TV"))
                _LOG.debug("Using device name: %s", device_name)
                
                _pairing_vizio_tv = pyvizio.Vizio(
                    device_id=unique_id,
                    ip=host,
                    name=device_name,
                    device_type=pyvizio.DEVICE_CLASS_TV
                )
                _LOG.debug("Created Vizio device instance: %s", _pairing_vizio_tv)
            except Exception as ex:
                _LOG.error("Error creating Vizio device instance: %s", ex)
                return SetupError(error_type=IntegrationSetupError.OTHER)
            
            # Check if we can connect to the device
            _LOG.debug("Checking if we can connect to the device")
            try:
                loop = asyncio.get_event_loop()
                can_connect = await loop.run_in_executor(_executor, _pairing_vizio_tv.can_connect_no_auth_check)
                _LOG.debug("Can connect: %s", can_connect)
                if not can_connect:
                    _LOG.error("Cannot connect to Vizio TV at %s", host)
                    return SetupError(error_type=IntegrationSetupError.CONNECTION_REFUSED)
            except Exception as ex:
                _LOG.error("Error checking connection to Vizio TV at %s: %s", host, ex)
                return SetupError(error_type=IntegrationSetupError.CONNECTION_REFUSED)
            
            # Start pairing process
            _LOG.debug("Starting pairing process")
            try:
                pair_data = await loop.run_in_executor(_executor, _pairing_vizio_tv.start_pair)
                _LOG.debug("Pairing data: %s", pair_data)
                if not pair_data:
                    _LOG.error("Failed to start pairing with Vizio TV at %s", host)
                    return SetupError(error_type=IntegrationSetupError.OTHER)
                # Store pairing tokens for use in handle_pairing
                global _pairing_challenge_type, _pairing_req_token
                _pairing_challenge_type = pair_data.ch_type
                _pairing_req_token = pair_data.token
                _LOG.debug("Stored pairing challenge_type=%s, req_token=%s", _pairing_challenge_type, _pairing_req_token)
            except Exception as ex:
                _LOG.error("Error starting pairing with Vizio TV at %s: %s", host, ex)
                return SetupError(error_type=IntegrationSetupError.OTHER)
            
            # Create a temporary config device
            _LOG.debug("Creating temporary config device")
            try:
                model_name = discovered_device.get("friendlyName", discovered_device.get("modelName", "Vizio TV"))
                _LOG.debug("Using model name: %s", model_name)
                
                _config_device = config.VizioDevice(
                    id=unique_id, 
                    name=model_name, 
                    address=host, 
                    key="",  # Will be set after pairing
                    mac_address=mac_address, 
                    mac_address2=mac_address2,
                    interface="0.0.0.0", 
                    broadcast=None, 
                    wol_port=9
                )
                _LOG.debug("Created temporary config device: %s", _config_device)
            except Exception as ex:
                _LOG.error("Error creating temporary config device: %s", ex)
                return SetupError(error_type=IntegrationSetupError.OTHER)
            
            # Move to pairing step
            _LOG.debug("Moving to PAIRING step")
            _setup_step = SetupSteps.PAIRING
            return RequestUserInput(
                title={"en": "Pair with Vizio TV"},
                settings=[
                    {
                        "id": "info",
                        "label": {"en": "Pair with Vizio TV"},
                        "field": {
                            "label": {
                                "value": {
                                    "en": "Enter the PIN displayed on your Vizio TV",
                                }
                            }
                        },
                    },
                    {
                        "field": {"text": {"value": ""}},
                        "id": "pin",
                        "label": {"en": "PIN"},
                    },
                ],
            )
            
        except Exception as ex:
            _LOG.error("Error connecting to Vizio TV at %s: %s", host, ex)
            return SetupError(error_type=IntegrationSetupError.CONNECTION_REFUSED)
    except StopIteration as ex:
        _LOG.error("StopIteration exception in handle_device_choice: %s", ex)
        return SetupError(error_type=IntegrationSetupError.OTHER)
    except Exception as ex:
        _LOG.error("Exception in handle_device_choice: %s", ex)
        return SetupError(error_type=IntegrationSetupError.OTHER)


async def handle_pairing(msg: UserDataResponse) -> RequestUserInput | SetupError:
    """
    Process user data response for pairing with Vizio TV.

    :param msg: response data from the requested user data
    :return: the setup action on how to continue
    """
    global _pairing_vizio_tv
    global _config_device
    global _setup_step
    
    try:
        _LOG.debug("Handling pairing step")
        
        # Check if _pairing_vizio_tv is initialized
        if not _pairing_vizio_tv:
            _LOG.error("Pairing TV object is not initialized")
            return SetupError(error_type=IntegrationSetupError.OTHER)
            
        # Check if _config_device is initialized
        if not _config_device:
            _LOG.error("Config device object is not initialized")
            return SetupError(error_type=IntegrationSetupError.OTHER)
        
        pin = msg.input_values.get("pin", "")
        
        if not pin:
            _LOG.error("PIN is required for pairing")
            return SetupError(error_type=IntegrationSetupError.OTHER)
        
        try:
            # Complete pairing with PIN
            _LOG.debug("Attempting to pair with PIN: %s", pin)
            loop = asyncio.get_event_loop()
            pair_result = await loop.run_in_executor(
                _executor, functools.partial(_pairing_vizio_tv.pair, _pairing_challenge_type, _pairing_req_token, pin)
            )
            if not pair_result:
                _LOG.error("Pairing result is None")
                return SetupError(error_type=IntegrationSetupError.OTHER)
                
            if not pair_result.auth_token:
                _LOG.error("Failed to pair with Vizio TV: No auth token received")
                return SetupError(error_type=IntegrationSetupError.OTHER)
            
            # Store the auth token
            _LOG.debug("Pairing successful, storing auth token")
            _config_device.key = pair_result.auth_token
            
            # Move to additional settings
            _LOG.debug("Moving to additional settings")
            return get_additional_settings(_config_device)
            
        except Exception as ex:
            _LOG.error("Error during pairing with Vizio TV: %s", ex)
            return SetupError(error_type=IntegrationSetupError.OTHER)
    except StopIteration as ex:
        _LOG.error("StopIteration exception in handle_pairing: %s", ex)
        return SetupError(error_type=IntegrationSetupError.OTHER)
    except Exception as ex:
        _LOG.error("Exception in handle_pairing: %s", ex)
        return SetupError(error_type=IntegrationSetupError.OTHER)


def get_additional_settings(config_device: config.VizioDevice) -> RequestUserInput:
    """
    Get additional settings for Vizio TV configuration.

    :param config_device: Vizio TV configuration
    :return: RequestUserInput for additional settings
    """
    global _setup_step
    _setup_step = SetupSteps.ADDITIONAL_SETTINGS
    if config_device.mac_address2 is None:
        config_device.mac_address2 = ""
    _LOG.debug("get_additional_settings")

    additional_fields = [
        {
            "id": "info",
            "label": {
                "en": "Additional settings",
            },
            "field": {
                "label": {
                    "value": {
                        "en": "MAC address is necessary to turn on the TV, check the displayed value",
                    }
                }
            },
        },
        {
            "field": {"text": {"value": config_device.address}},
            "id": "address",
            "label": {"en": "IP address"},
        },
        {
            "field": {"text": {"value": config_device.mac_address}},
            "id": "mac_address",
            "label": {"en": "MAC address (wired)"},
        },
        {
            "field": {"text": {"value": config_device.mac_address2}},
            "id": "mac_address2",
            "label": {"en": "MAC address (wifi)"},
        },
        {
            "field": {"text": {"value": config_device.interface}},
            "id": "interface",
            "label": {"en": "Interface to use for magic packet"},
        },
        {
            "field": {"text": {"value": config_device.broadcast}},
            "id": "broadcast",
            "label": {"en": "Broadcast address to use for magic packet (blank by default)"},
        },
        {
            "id": "wolport",
            "label": {
                "en": "Wake on LAN port",
            },
            "field": {
                "number": {"value": config_device.wol_port, "min": 1, "max": 65535, "steps": 1, "decimals": 0}
            },
        },
        {
            "id": "test_wakeonlan",
            "label": {
                "en": "Test turn on your configured TV (through Wake-on-LAN, TV should be off since 15 minutes at least)",
            },
            "field": {"checkbox": {"value": False}},
        },
    ]

    return RequestUserInput(
        title={
            "en": "Additional settings",
        },
        settings=additional_fields
    )


def _is_ipv6_address(ip_address: str) -> bool:
    """
    Check if an IP address is IPv6.

    :param ip_address: IP address to check
    :return: True if IPv6, False otherwise
    """
    try:
        return isinstance(ipaddress.ip_address(ip_address), ipaddress.IPv6Address)
    except ValueError:
        return False


def get_wakeonlan_settings() -> RequestUserInput:
    """
    Get Wake-on-LAN settings for Vizio TV.

    :return: RequestUserInput for Wake-on-LAN settings
    """
    global _config_device

    broadcast = ""
    try:
        interface = os.getenv("UC_INTEGRATION_INTERFACE")
        if interface is None or interface == "127.0.0.1":
            interface = None
            ips = [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None)]
            for ip_addr in ips:
                if ip_addr is None or ip_addr == "127.0.0.1" or _is_ipv6_address(ip_addr):
                    continue
                interface = ip_addr
                break
        if interface is not None:
            broadcast = interface[:interface.rfind('.') + 1] + '255'
    except Exception:
        pass

    return RequestUserInput(
        title={
            "en": "Test switching on your Vizio TV",
        },
        settings=[{
            "id": "info",
            "label": {
                "en": "Test switching on your Vizio TV",
            },
            "field": {
                "label": {
                    "value": {
                        "en": f"Remote interface {interface} : suggested broadcast {broadcast}",
                    }
                }
            },
        },
            {
                "field": {"text": {"value": _config_device.mac_address}},
                "id": "mac_address",
                "label": {"en": "First MAC address"},
            },
            {
                "field": {"text": {"value": _config_device.mac_address2}},
                "id": "mac_address2",
                "label": {"en": "Second MAC address"},
            },
            {
                "field": {"text": {"value": _config_device.interface}},
                "id": "interface",
                "label": {"en": "Interface (optional)"},
            },
            {
                "field": {"text": {"value": _config_device.broadcast}},
                "id": "broadcast",
                "label": {"en": "Broadcast (optional)"},
            },
            {
                "id": "wolport",
                "label": {
                    "en": "Wake on LAN port",
                },
                "field": {
                    "number": {"value": _config_device.wol_port, "min": 1, "max": 65535, "steps": 1, "decimals": 0}
                },
            },
        ]
    )


async def handle_additional_settings(msg: UserDataResponse) -> RequestUserConfirmation | SetupComplete | SetupError:
    """
    Handle additional settings for Vizio TV.

    :param msg: response data from the requested user data
    :return: the setup action on how to continue
    """
    global _config_device
    global _pairing_vizio_tv
    global _setup_step
    address = msg.input_values.get("address", "")
    mac_address = msg.input_values.get("mac_address", "")
    mac_address2 = msg.input_values.get("mac_address2", "")
    interface  = msg.input_values.get("interface", "")
    broadcast = msg.input_values.get("broadcast", "")
    test_wakeonlan = msg.input_values.get("test_wakeonlan", "false") == "true"
    try:
        wolport = int(msg.input_values.get("wolport", 9))
    except ValueError:
        return SetupError(error_type=IntegrationSetupError.OTHER)

    if address != "":
        _config_device.address = address
    if mac_address == "":
        mac_address = None
    if mac_address2 == "":
        mac_address2 = None
    if broadcast == "":
        broadcast = None
    if interface == "":
        interface = None

    _config_device.mac_address = mac_address
    _config_device.mac_address2 = mac_address2
    _config_device.interface = interface
    _config_device.broadcast = broadcast
    _config_device.wol_port = wolport

    _LOG.info("Setup updated settings %s", _config_device)
    config.devices.add_or_update(_config_device)
    # triggers Vizio TV instance creation

    if _pairing_vizio_tv:
        _pairing_vizio_tv = None

    if test_wakeonlan:
        _setup_step = SetupSteps.TEST_WAKEONLAN
        return await handle_wake_on_lan(msg)

    # Vizio TV device connection will be triggered with subscribe_entities request
    await asyncio.sleep(1)
    _LOG.info("Setup successfully completed for %s (%s)", _config_device.name, _config_device.id)
    return SetupComplete()


async def handle_wake_on_lan(msg: UserDataResponse) -> RequestUserConfirmation | SetupError:
    """
    Handle Wake-on-LAN test for Vizio TV.

    :param msg: response data from the requested user data
    :return: the setup action on how to continue
    """
    global _config_device
    mac_address = msg.input_values.get("mac_address", "")
    mac_address2 = msg.input_values.get("mac_address2", "")
    interface = msg.input_values.get("interface", "")
    broadcast = msg.input_values.get("broadcast", "")
    wolport = 9
    try:
        wolport = int(msg.input_values.get("wolport", wolport))
    except ValueError:
        return SetupError(error_type=IntegrationSetupError.OTHER)

    if mac_address == "":
        mac_address = None
    if mac_address2 == "":
        mac_address2 = None
    if broadcast == "":
        broadcast = None
    if interface == "":
        interface = None

    _config_device.mac_address = mac_address
    _config_device.mac_address2 = mac_address2
    _config_device.interface = interface
    _config_device.broadcast = broadcast
    _config_device.wol_port = wolport

    _LOG.info("Setup updated settings %s", _config_device)
    config.devices.add_or_update(_config_device)
    # triggers Vizio TV instance creation
    config.devices.store()

    requests = 0
    if _config_device.mac_address:
        requests += 1
    if _config_device.mac_address2:
        requests += 1

    device = tv.VizioTv(device_config=_config_device)
    device.wakeonlan()

    return RequestUserConfirmation(title={
            "en": f"{requests} requests sent to the TV",
        },
        header={
            "en": "Do you want to try another configuration?",
        }
    )