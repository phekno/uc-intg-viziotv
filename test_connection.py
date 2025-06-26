import asyncio
import logging
import tabulate
import sys

import pyvizio
from pyvizio import VizioAsync, guess_device_type
from pyvizio.const import (
    DEFAULT_TIMEOUT,
)

# _LOOP = asyncio.new_event_loop()
# asyncio.set_event_loop(_LOOP)
    
# async def main():
#     include_device_type = False
#     devices = VizioAsync.discovery_zeroconf(DEFAULT_TIMEOUT)

#     data = []

#     if devices:
#         data = [
#             {"IP": dev.ip, "Port": dev.port, "Model": dev.model, "Name": dev.name}
#             for dev in devices
#         ]
#     else:
#         _LOG.info("Couldn't find any devices using zeroconf, trying SSDP")
#         devices = VizioAsync.discovery_ssdp(DEFAULT_TIMEOUT)
#         if devices:
#             data = [
#                 {"IP": dev.ip, "Model": dev.model, "Name": dev.name} for dev in devices
#             ]

#     if devices:
#         if include_device_type:
#             for dev in data:
#                 dev["Guessed Device Type"] = guess_device_type(
#                     dev["IP"], dev.get("Port")
#                 )

#         _LOG.info("\n%s", tabulate(data, "keys"))
#     else:
#         _LOG.info("No Vizio devices discoverd.")
    

# if __name__ == "__main__":
#     _LOG = logging.getLogger(__name__)
#     formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
#     ch = logging.StreamHandler()
#     ch.setFormatter(formatter)
#     logging.basicConfig(handlers=[ch])
#     logging.getLogger("client").setLevel(logging.DEBUG)
#     logging.getLogger("lg").setLevel(logging.DEBUG)
#     logging.getLogger(__name__).setLevel(logging.DEBUG)
#     _LOOP.run_until_complete(main())
#     _LOOP.run_forever()

_LOG = logging.getLogger()
include_device_type = True
zeroconf_devices = VizioAsync.discovery_zeroconf(DEFAULT_TIMEOUT)
ssdp_devices = VizioAsync.discovery_ssdp(DEFAULT_TIMEOUT)

print(zeroconf_devices)
print(ssdp_devices)

# data = []

# if devices:
#     data = [
#         {"IP": dev.ip, "Port": dev.port, "Model": dev.model, "Name": dev.name}
#         for dev in devices
#     ]
# else:
#     _LOG.info("Couldn't find any devices using zeroconf, trying SSDP")
#     devices = VizioAsync.discovery_ssdp(DEFAULT_TIMEOUT)
#     if devices:
#         data = [
#             {"IP": dev.ip, "Model": dev.model, "Name": dev.name} for dev in devices
#         ]

# if devices:
#     if include_device_type:
#         for dev in data:
#             dev["Guessed Device Type"] = guess_device_type(
#                 dev["IP"], dev.get("Port")
#             )

#     _LOG.info("\n%s", tabulate.tabulate(data, "keys"))
# else:
#     _LOG.info("No Vizio devices discoverd.")