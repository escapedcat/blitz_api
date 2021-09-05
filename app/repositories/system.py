import asyncio

import psutil
from app.models.system import SystemInfo
from app.repositories.lightning import get_ln_info
from app.utils import SSE, send_sse_message
from decouple import config
from fastapi import Request

SLEEP_TIME = config("gather_hw_info_interval", default=2, cast=float)
CPU_AVG_PERIOD = config("cpu_usage_averaging_period", default=0.5, cast=float)
HW_INFO_YIELD_TIME = SLEEP_TIME + CPU_AVG_PERIOD


async def get_system_info() -> SystemInfo:
    lninfo = await get_ln_info()
    return SystemInfo.from_rpc(lninfo)


async def subscribe_hardware_info(request: Request):
    while True:
        if await request.is_disconnected():
            # stop if client disconnects
            break
        yield get_hardware_info()
        await asyncio.sleep(SLEEP_TIME)


def get_hardware_info() -> map:
    info = {}

    info["cpu_overall_percent"] = psutil.cpu_percent(interval=CPU_AVG_PERIOD)
    info["cpu_per_cpu_percent"] = psutil.cpu_percent(
        interval=CPU_AVG_PERIOD, percpu=True
    )

    v = psutil.virtual_memory()
    info["vram_total_bytes"] = v.total
    info["vram_available_bytes"] = v.available
    info["vram_used_bytes"] = v.used
    info["vram_usage_percent"] = v.percent

    s = psutil.swap_memory()
    info["swap_ram_total_bytes"] = s.total
    info["swap_used_bytes"] = s.used
    info["swap_usage_bytes"] = s.percent

    info["temperatures_celsius"] = psutil.sensors_temperatures()
    info["boot_time_timestamp"] = psutil.boot_time()

    disk_io = psutil.disk_io_counters()
    info["disk_io_read_count"] = disk_io.read_count
    info["disk_io_write_count"] = disk_io.write_count
    info["disk_io_read_bytes"] = disk_io.read_bytes
    info["disk_io_write_bytes"] = disk_io.write_bytes

    disks = []
    partitions = psutil.disk_partitions()
    for partition in partitions:
        p = {}
        p["device"] = partition.device
        p["mountpoint"] = partition.mountpoint
        p["filesystem_type"] = partition.fstype

        try:
            usage = psutil.disk_usage(partition.mountpoint)
            p["partition_total_bytes"] = usage.total
            p["partition_used_bytes"] = usage.used
            p["partition_free_bytes"] = usage.free
            p["partition_percent"] = usage.percent
        except PermissionError:
            continue
        disks.append(p)
    info["disks"] = disks

    nets = []
    addresses = psutil.net_if_addrs()
    for name, address in addresses.items():
        net = {}
        nets.append(net)
        net["interface_name"] = name
        for a in address:
            if str(a.family) == "AddressFamily.AF_INET":
                net["address"] = a.address
            elif str(a.family) == "AddressFamily.AF_PACKET":
                net["mac_address"] = a.address

    net_io = psutil.net_io_counters()
    info["networks"] = nets
    info["networks_bytes_sent"] = net_io.bytes_sent
    info["networks_bytes_received"] = net_io.bytes_recv

    return info


async def _handle_gather_hardware_info():
    last_info = {}
    while True:
        info = get_hardware_info()
        if last_info != info:
            await send_sse_message(SSE.SYS_STATUS, info)
            last_info = info

        await asyncio.sleep(HW_INFO_YIELD_TIME)


async def register_hardware_info_gatherer():
    loop = asyncio.get_event_loop()
    loop.create_task(_handle_gather_hardware_info())