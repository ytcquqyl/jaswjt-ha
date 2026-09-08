"""The 吉安水务 (Ji'an Water Service) integration for Home Assistant."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import BillRecord, JaswjtClient, SessionExpired
from .const import CONF_ACCOUNTS, CONF_SESSION_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

DEFAULT_SCAN_INTERVAL = timedelta(minutes=15)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up 吉安水务 from a config entry."""
    client = JaswjtClient(
        session_id=entry.data[CONF_SESSION_ID],
        accounts=entry.data[CONF_ACCOUNTS],
    )

    async def _async_update() -> dict[str, list[BillRecord]]:
        try:
            fresh = await client.fetch_bills()
        except SessionExpired as exc:
            # Session is dead - report clearly, but keep the entry loaded so the
            # user can fix the session id without a full re-add.
            _LOGGER.warning("吉安水务会话已失效: %s", exc)
            raise UpdateFailed(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - coordinator needs a catch-all
            _LOGGER.warning("吉安水务数据更新失败: %s", exc)
            raise UpdateFailed(str(exc)) from exc

        # 累积历史: API 只返回最近 N 个月(当前是 5 个), 旧月份下次刷新就不
        # 再返回了。如果不合并, 历史传感器的数据会丢失(state 变 unknown)。
        # 这里把新数据合并到已有数据里, 同一月份以新数据为准(覆盖)。
        previous = coordinator.data or {}
        merged: dict[str, list[BillRecord]] = {}
        for account in client.accounts:
            by_month: dict[str, BillRecord] = {}
            for bill in previous.get(account, []):
                by_month[bill.month] = bill
            for bill in fresh.get(account, []):
                by_month[bill.month] = bill
            merged[account] = sorted(
                by_month.values(), key=lambda r: r.month, reverse=True
            )
        return merged

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{entry.entry_id}",
        update_method=_async_update,
        config_entry=entry,
        update_interval=DEFAULT_SCAN_INTERVAL,
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        raise
    except UpdateFailed as exc:
        # First refresh failed (e.g. session expired on day one).
        # Raise so HA marks the entry as "needs setup" rather than creating a
        # half-broken integration with no data.
        _LOGGER.error("吉安水务初始化失败: %s", exc)
        raise ConfigEntryNotReady(f"首次数据获取失败: {exc}") from exc

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # 不在这里调 async_get_or_create: HA 2026.7 的 DeviceRegistry 已移除
    # domain 参数, 且每个实体自带 _attr_device_info, 设备注册会自动完成.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
