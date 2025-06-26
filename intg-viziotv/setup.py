"""
Setup flow for Vizio TV integration.

:copyright: (c) 2023 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import asyncio
import ipaddress
import logging
import os
import socket
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


# pylint: disable = W1405


class SetupSteps(IntEnum):
    """Enumeration of setup steps to keep track of user data responses."""

    INIT = 0
    CONFIGURATION_MODE = 1
    DISCOVER = 2
    DEVICE_CHOICE = 3


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

_user_input_manual = RequestUserInput(
    {"en": "Samsung TV Setup"},
    [
        {
            "id": "info",
            "label": {
                "en": "Setup your Samsung TV",
            },
            "field": {
                "label": {
                    "value": {
                        "en": (
                            "Please supply the IP address or Hostname of your Samsung TV."
                        ),
                    }
                }
            },
        },
        {
            "field": {"text": {"value": ""}},
            "id": "ip",
            "label": {
                "en": "IP Address",
            },
        },
    ],
)


async def driver_setup_handler(
    msg: SetupDriver,
) -> SetupAction:  # pylint: disable=too-many-return-statements
    """
    Dispatch driver setup requests to corresponding handlers.

    Either start the setup process or handle the selected Apple TV device.

    :param msg: the setup driver request object, either DriverSetupRequest or UserDataResponse
    :return: the setup action on how to continue
    """
    global _setup_step  # pylint: disable=global-statement
    global _cfg_add_device  # pylint: disable=global-statement

    if isinstance(msg, DriverSetupRequest):
        _setup_step = SetupSteps.INIT
        _cfg_add_device = False
        return await _handle_driver_setup(msg)

    if isinstance(msg, UserDataResponse):
        _LOG.debug("%s", msg)
        if (
            _setup_step == SetupSteps.CONFIGURATION_MODE
            and "action" in msg.input_values
        ):
            return await _handle_configuration_mode(msg)
        if (
            _setup_step == SetupSteps.DISCOVER
            and "ip" in msg.input_values
            and msg.input_values.get("ip") != "manual"
        ):
            return await _handle_creation(msg)
        if (
            _setup_step == SetupSteps.DISCOVER
            and "ip" in msg.input_values
            and msg.input_values.get("ip") == "manual"
        ):
            return await _handle_manual()
        _LOG.error("No user input was received for step: %s", msg)
    elif isinstance(msg, AbortDriverSetup):
        _LOG.info("Setup was aborted with code: %s", msg.error)
        _setup_step = SetupSteps.INIT

    return SetupError()

async def _handle_driver_setup(
    msg: DriverSetupRequest,
) -> RequestUserInput | SetupError:
    """
    Start driver setup.

    Initiated by Remote Two to set up the driver. The reconfigure flag determines the setup flow:

    - Reconfigure is True:
        show the configured devices and ask user what action to perform (add, delete, reset).
    - Reconfigure is False: clear the existing configuration and show device discovery screen.
      Ask user to enter ip-address for manual configuration, otherwise auto-discovery is used.

    :param msg: driver setup request data, only `reconfigure` flag is of interest.
    :return: the setup action on how to continue
    """
    global _setup_step  # pylint: disable=global-statement

    reconfigure = msg.reconfigure
    _LOG.debug("Starting driver setup, reconfigure=%s", reconfigure)

    if reconfigure:
        _setup_step = SetupSteps.CONFIGURATION_MODE

        # get all configured devices for the user to choose from
        dropdown_devices = []
        for device in config.devices.all():
            dropdown_devices.append(
                {"id": device.identifier, "label": {"en": f"{device.name}"}}
            )

        dropdown_actions = [
            {
                "id": "add",
                "label": {
                    "en": "Add a new Vizio TV",
                },
            },
        ]

        # add remove & reset actions if there's at least one configured device
        if dropdown_devices:
            dropdown_actions.append(
                {
                    "id": "update",
                    "label": {
                        "en": "Update information for selected Vizio TV",
                    },
                },
            )
            dropdown_actions.append(
                {
                    "id": "remove",
                    "label": {
                        "en": "Remove selected Vizio TV",
                    },
                },
            )
            dropdown_actions.append(
                {
                    "id": "reset",
                    "label": {
                        "en": "Reset configuration and reconfigure",
                        "de": "Konfiguration zurücksetzen und neu konfigurieren",
                        "fr": "Réinitialiser la configuration et reconfigurer",
                    },
                },
            )
        else:
            # dummy entry if no devices are available
            dropdown_devices.append({"id": "", "label": {"en": "---"}})

        return RequestUserInput(
            {"en": "Configuration mode", "de": "Konfigurations-Modus"},
            [
                {
                    "field": {
                        "dropdown": {
                            "value": dropdown_devices[0]["id"],
                            "items": dropdown_devices,
                        }
                    },
                    "id": "choice",
                    "label": {
                        "en": "Configured Devices",
                        "de": "Konfigurerte Geräte",
                        "fr": "Appareils configurés",
                    },
                },
                {
                    "field": {
                        "dropdown": {
                            "value": dropdown_actions[0]["id"],
                            "items": dropdown_actions,
                        }
                    },
                    "id": "action",
                    "label": {
                        "en": "Action",
                        "de": "Aktion",
                        "fr": "Appareils configurés",
                    },
                },
            ],
        )

    # Initial setup, make sure we have a clean configuration
    config.devices.clear()  # triggers device instance removal
    _setup_step = SetupSteps.DISCOVER
    return await _handle_discovery()


async def _handle_configuration_mode(
    msg: UserDataResponse,
) -> RequestUserInput | SetupComplete | SetupError:
    """
    Process user data response from the configuration mode screen.

    User input data:

    - ``choice`` contains identifier of selected device
    - ``action`` contains the selected action identifier

    :param msg: user input data from the configuration mode screen.
    :return: the setup action on how to continue
    """
    global _setup_step  # pylint: disable=global-statement
    global _cfg_add_device  # pylint: disable=global-statement

    action = msg.input_values["action"]

    # workaround for web-configurator not picking up first response
    await asyncio.sleep(1)

    match action:
        case "add":
            _cfg_add_device = True
            _setup_step = SetupSteps.DISCOVER
            return await _handle_discovery()
        case "update":
            choice = msg.input_values["choice"]
            if not config.devices.remove(choice):
                _LOG.warning("Could not update device from configuration: %s", choice)
                return SetupError(error_type=IntegrationSetupError.OTHER)
            _setup_step = SetupSteps.DISCOVER
            return await _handle_discovery()
        case "remove":
            choice = msg.input_values["choice"]
            if not config.devices.remove(choice):
                _LOG.warning("Could not remove device from configuration: %s", choice)
                return SetupError(error_type=IntegrationSetupError.OTHER)
            config.devices.store()
            return SetupComplete()
        case "reset":
            config.devices.clear()  # triggers device instance removal
            _setup_step = SetupSteps.DISCOVER
            return await _handle_discovery()
        case _:
            _LOG.error("Invalid configuration action: %s", action)
            return SetupError(error_type=IntegrationSetupError.OTHER)

    _setup_step = SetupSteps.DISCOVER
    return _user_input_manual


async def _handle_manual() -> RequestUserInput | SetupError:
    return _user_input_manual


async def _handle_discovery() -> RequestUserInput | SetupError:
    """
    Process user data response from the first setup process screen.
    """
    global _setup_step  # pylint: disable=global-statement
    global _discovered_devices

    address = msg.input_values.get("address", "")

    await asyncio.sleep(1)

    if address:
        try:
            device_type = pyvizio.guess_device_type(address)
            if device_type != pyvizio.DEVICE_CLASS_TV:
                _LOG.warning("Device at %s is not a Vizio TV", address)
                return SetupError(error_type=IntegrationSetupError.DEVICE_NOT_FOUND)
            
            # Create a device entry
            _discovered_devices = [{"host": address, "modelName": "Vizio TV", "friendlyName": "Vizio TV"}]
            
        except Exception as ex:
            _LOG.error("Cannot connect to %s: %s", address, ex)
            return SetupError(error_type=IntegrationSetupError.CONNECTION_REFUSED)

    else:
        # Auto-discovery: find Vizio TVs on the network
        try:
            _discovered_devices = await discover.async_identify_vizio_devices()
            if not _discovered_devices:
                _LOG.warning("No Vizio TVs found on the network")
                return SetupError(error_type=IntegrationSetupError.DEVICE_NOT_FOUND)
        except Exception as ex:
            _LOG.error("Error during Vizio TV discovery: %s", ex)
            return SetupError(error_type=IntegrationSetupError.OTHER)

    # Present the discovered devices to the user
    _setup_step = SetupSteps.DEVICE_CHOICE
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
                    "select": {
                        "value": _discovered_devices[0]["host"],
                        "options": [
                            {
                                "id": device["host"],
                                "label": {"en": f"{device.get('friendlyName', device.get('modelName', 'Vizio TV'))} ({device['host']})"},
                            }
                            for device in _discovered_devices
                        ],
                    }
                },
            },
        ],
    )


async def _handle_creation(msg: UserDataResponse) -> RequestUserInput | SetupError:
    """
    Process user data response from the first setup process screen.

    :param msg: response data from the requested user data
    :return: the setup action on how to continue
    """
    reports_power_state = False
    ip = msg.input_values["ip"]
    if ip is not None and ip != "":
        _LOG.debug("Connecting to Vizio TV at %s", ip)

        tv = SamsungTVWS(
            ip,
            port=8002,
            timeout=30,
            name="Unfolded Circle",
        )

        info = tv.rest_device_info()

        if info and info.get("device", None).get("PowerState", None) is not None:
            reports_power_state = True

        _LOG.info("Samsung TV info: %s", info)

    # if we are adding a new device: make sure it's not already configured
    if _cfg_add_device and config.devices.contains(info.get("identifier")):
        _LOG.info(
            "Skipping found device %s: already configured",
            info.get("device").get("name"),
        )
        return SetupError(error_type=IntegrationSetupError.OTHER)
    name = re.sub(r"^\[TV\] ", "", info.get("device").get("name"))
    device = SamsungDevice(
        identifier=info.get("id"),
        name=name,
        token=tv.token,
        address=ip,
        mac_address=info.get("device").get(
            "wifiMac"
        ),  # Both wired and wireless use the same key
        reports_power_state=reports_power_state,
    )
    tv.close()
    config.devices.add_or_update(device)

    await asyncio.sleep(1)

    _LOG.info("Setup successfully completed for %s [%s]", device.name, device)

    return SetupComplete()


async def handle_driver_setup(msg: DriverSetupRequest) -> RequestUserInput | SetupError:
    """
    Start driver setup.

    Initiated by Remote Two to set up the driver.
    Ask user to enter ip-address for manual configuration, otherwise auto-discovery is used.

    :param msg: not used, we don't have any input fields in the first setup screen.
    :return: the setup action on how to continue
    """
    await asyncio.sleep(1)

    if msg.reconfigure:
        print("Ignoring driver reconfiguration request")
    
    # If we have configured devices, show configuration mode
    if config.devices.all():
        _setup_step = SetupSteps.CONFIGURATION_MODE
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
                        "select": {
                            "value": "add",
                            "options": [
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
                            "select": {
                                "value": next(iter(config.devices.all())).id,
                                "options": [
                                    {
                                        "id": device.id,
                                        "label": {"en": f"{device.name} ({device.address})"},
                                    }
                                    for device in config.devices.all()
                                ],
                            }
                        },
                    }
                ]
                if config.devices.all()
                else []
            ),
        )

    # No configured devices, go straight to discovery
    _setup_step = SetupSteps.DISCOVER
    return _user_input_discovery


async def handle_user_data_response(msg: UserDataResponse) -> SetupAction:
    """
    Process user data response in a setup process.

    Driver setup callback to provide requested user data during the setup process.

    :param msg: response data from the requested user data
    :return: the setup action on how to continue
    """
    global _setup_step

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

    address = msg.input_values.get("address", "")

    # workaround for web-configurator not picking up first response
    await asyncio.sleep(1)

    if address:
        # Manual configuration: try to connect to the given address
        try:
            # Check if we can connect to the device
            device_type = pyvizio.guess_device_type(address)
            if device_type != pyvizio.DEVICE_CLASS_TV:
                _LOG.warning("Device at %s is not a Vizio TV", address)
                return SetupError(error_type=IntegrationSetupError.DEVICE_NOT_FOUND)
            
            # Create a device entry
            _discovered_devices = [{"host": address, "modelName": "Vizio TV", "friendlyName": "Vizio TV"}]
            
        except Exception as ex:
            _LOG.error("Cannot connect to %s: %s", address, ex)
            return SetupError(error_type=IntegrationSetupError.CONNECTION_REFUSED)
    else:
        # Auto-discovery: find Vizio TVs on the network
        try:
            _discovered_devices = await discover.async_identify_vizio_devices()
            if not _discovered_devices:
                _LOG.warning("No Vizio TVs found on the network")
                return SetupError(error_type=IntegrationSetupError.DEVICE_NOT_FOUND)
        except Exception as ex:
            _LOG.error("Error during Vizio TV discovery: %s", ex)
            return SetupError(error_type=IntegrationSetupError.OTHER)

    # Present the discovered devices to the user
    _setup_step = SetupSteps.DEVICE_CHOICE
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
                    "select": {
                        "value": _discovered_devices[0]["host"],
                        "options": [
                            {
                                "id": device["host"],
                                "label": {"en": f"{device.get('friendlyName', device.get('modelName', 'Vizio TV'))} ({device['host']})"},
                            }
                            for device in _discovered_devices
                        ],
                    }
                },
            },
        ],
    )


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
    discovered_device = None
    host = msg.input_values["choice"]
    mac_address = None
    mac_address2 = None

    if _discovered_devices:
        for device in _discovered_devices:
            if device.get("host", None) == host:
                discovered_device = device
                if device.get("wiredMac"):
                    mac_address = device.get("wiredMac")
                if device.get("wifiMac"):
                    mac_address2 = device.get("wifiMac")

    _LOG.debug("Chosen Vizio TV: %s (wired mac %s, wifi mac %s). Trying to connect and retrieve device information...",
               host, mac_address, mac_address2)
    
    try:
        # Get a unique ID for the device
        unique_id = await pyvizio.VizioAsync.get_unique_id(host, pyvizio.DEVICE_CLASS_TV)
        if not unique_id:
            _LOG.error("Could not get unique ID for Vizio TV at %s", host)
            return SetupError(error_type=IntegrationSetupError.OTHER)
        
        # Create a Vizio device instance
        _pairing_vizio_tv = pyvizio.Vizio(
            device_id=unique_id,
            ip=host,
            name=discovered_device.get("friendlyName", discovered_device.get("modelName", "Vizio TV")),
            device_type=pyvizio.DEVICE_CLASS_TV
        )
        
        # Check if we can connect to the device
        if not _pairing_vizio_tv.can_connect_no_auth_check():
            _LOG.error("Cannot connect to Vizio TV at %s", host)
            return SetupError(error_type=IntegrationSetupError.CONNECTION_REFUSED)
        
        # Start pairing process
        pair_data = _pairing_vizio_tv.start_pair()
        if not pair_data:
            _LOG.error("Failed to start pairing with Vizio TV at %s", host)
            return SetupError(error_type=IntegrationSetupError.OTHER)
        
        # Create a temporary config device
        model_name = discovered_device.get("friendlyName", discovered_device.get("modelName", "Vizio TV"))
        _config_device = config.VizioConfigDevice(
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
        
        # Move to pairing step
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


async def handle_pairing(msg: UserDataResponse) -> RequestUserInput | SetupError:
    """
    Process user data response for pairing with Vizio TV.

    :param msg: response data from the requested user data
    :return: the setup action on how to continue
    """
    global _pairing_vizio_tv
    global _config_device
    global _setup_step
    
    pin = msg.input_values.get("pin", "")
    
    if not pin:
        _LOG.error("PIN is required for pairing")
        return SetupError(error_type=IntegrationSetupError.OTHER)
    
    try:
        # Complete pairing with PIN
        pair_result = _pairing_vizio_tv.pair(1, "1", pin)
        if not pair_result or not pair_result.auth_token:
            _LOG.error("Failed to pair with Vizio TV: Invalid PIN")
            return SetupError(error_type=IntegrationSetupError.OTHER)
        
        # Store the auth token
        _config_device.key = pair_result.auth_token
        
        # Move to additional settings
        return get_additional_settings(_config_device)
        
    except Exception as ex:
        _LOG.error("Error during pairing with Vizio TV: %s", ex)
        return SetupError(error_type=IntegrationSetupError.OTHER)


def get_additional_settings(config_device: config.VizioConfigDevice) -> RequestUserInput:
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