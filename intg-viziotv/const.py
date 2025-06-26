"""Constants used for Vizio SmartCast TV."""

from enum import Enum, IntEnum

from ucapi.media_player import Features
from ucapi.ui import DeviceButtonMapping, Buttons, UiPage


class EVENTS(IntEnum):
    """Internal driver events."""

    CONNECTING = 0
    CONNECTED = 1
    DISCONNECTED = 2
    PAIRED = 3
    ERROR = 4
    UPDATE = 5


class PowerState(str, Enum):
    """Power state for Vizio TV."""

    OFF = "OFF"
    ON = "ON"
    STANDBY = "STANDBY"


class SimpleCommands(str, Enum):
    """Simple commands for Vizio TV."""

    EXIT = "exit"
    CH_LIST = "ch_list"
    SLEEP = "sleep"
    HDMI_1 = "hdmi_1"
    HDMI_2 = "hdmi_2"
    HDMI_3 = "hdmi_3"
    HDMI_4 = "hdmi_4"
    DEVICE_INFO = "device_info"


# Mapping of Vizio remote keys to their corresponding codes
VIZIO_KEY_MAPPING = {
    "VOLUME_UP": "VOLUME_UP",
    "VOLUME_DOWN": "VOLUME_DOWN",
    "MUTE": "MUTE",
    "POWER": "POWER",
    "UP": "UP",
    "DOWN": "DOWN",
    "LEFT": "LEFT",
    "RIGHT": "RIGHT",
    "OK": "OK",
    "BACK": "BACK",
    "HOME": "HOME",
    "MENU": "MENU",
    "INFO": "INFO",
    "GUIDE": "GUIDE",
    "ENTER": "ENTER",
    "EXIT": "EXIT",
    "PLAY": "PLAY",
    "PAUSE": "PAUSE",
    "STOP": "STOP",
    "FORWARD": "FORWARD",
    "REWIND": "REWIND",
    "RECORD": "RECORD",
    "CHANNEL_UP": "CH_UP",
    "CHANNEL_DOWN": "CH_DOWN",
    "PREVIOUS": "PREVIOUS",
    "0": "0",
    "1": "1",
    "2": "2",
    "3": "3",
    "4": "4",
    "5": "5",
    "6": "6",
    "7": "7",
    "8": "8",
    "9": "9",
}