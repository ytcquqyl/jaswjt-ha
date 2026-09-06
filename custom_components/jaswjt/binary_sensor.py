"""Binary sensor platform for 吉安水务: unpaid-bill indicator."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .client import BillRecord
from .const import CONF_ACCOUNTS, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """One unpaid indicator per account."""
    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    accounts: list[str] = list(entry.data[CONF_ACCOUNTS])

    entities: list[BinarySensorEntity] = []
    for account in accounts:
        # 设备名逻辑与 sensor.py 保持一致(否则同一设备在两个平台注册名不同)
        bills = coordinator.data.get(account, [])
        label = account
        if bills and bills[0].address:
            label = bills[0].address
        elif bills and bills[0].owner:
            label = bills[0].owner
        device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}:{account}")},
            name=f"吉安水务 {label}",
            manufacturer="吉安水务集团有限公司",
            model="水费查询",
            sw_version=f"户号 {account}",
        )
        entities.append(JaswjtUnpaidSensor(coordinator, entry.entry_id, account, device_info))

    async_add_entities(entities)


class JaswjtUnpaidSensor(CoordinatorEntity, BinarySensorEntity):
    """On when the latest bill for this account has not been paid yet."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "是否欠费"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry_id: str,
        account: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._account = account
        self._attr_device_info = device_info
        self._attr_unique_id = f"{entry_id}:{account}:unpaid"

    @property
    def _latest(self) -> BillRecord | None:
        bills = self.coordinator.data.get(self._account, [])
        return bills[0] if bills else None

    @property
    def is_on(self) -> bool:
        """True when the newest bill is unpaid (费用状态 == 'Q')."""
        rec = self._latest
        if rec is None:
            return False
        return not rec.paid

    @property
    def extra_state_attributes(self) -> dict:
        rec = self._latest
        if rec is None:
            return {}
        return {
            "户号": rec.account,
            "户名": rec.owner,
            "地址": rec.address,
            "月份": rec.month_label,
            "费用合计": rec.total_fee,
            "状态代码": rec.status_code,
        }
