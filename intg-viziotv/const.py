"""Constants used for Vizio SmartCast TV."""

from enum import Enum, IntEnum


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
    INPUT_TV = "input_tv"
    INPUT_CAST = "input_cast"
    DEVICE_INFO = "device_info"


# Mapping of Vizio remote keys to their corresponding codes
VIZIO_KEY_MAPPING = {
    "VOLUME_UP": "VOL_UP",
    "VOLUME_DOWN": "VOL_DOWN",
    "MUTE": "MUTE_TOGGLE",
    "POWER": "POW_TOGGLE",
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
    "ENTER": "OK",
    "EXIT": "EXIT",
    "PLAY": "PLAY",
    "PAUSE": "PAUSE",
    "STOP": "STOP",
    "FORWARD": "SEEK_FWD",
    "REWIND": "SEEK_BACK",
    "CHANNEL_UP": "CH_UP",
    "CHANNEL_DOWN": "CH_DOWN",
    "PREVIOUS": "PREV_CH",
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
