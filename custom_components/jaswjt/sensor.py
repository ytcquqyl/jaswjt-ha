"""Sensor platform for the 吉安水务 (Ji'an Water Service) integration.

两个传感器组:

1. 当月传感器 (JaswjtSensor): 每个 BILL_FIELDS 字段一个, 始终反映最新月。
2. 历史传感器 (JaswjtHistoricalSensor): 对 HISTORICAL_FIELDS 里的核心指标,
   API 返回的每一条账单(每个月)生成一个独立 sensor。HA recorder 会自动把
   state 变化持久化到 SQLite, 实现历史数据长期保存。

API 返回结构: {account: [BillRecord(最新), BillRecord, ...]} —— 已按月份倒序。
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .client import BillRecord, month_to_dt
from .const import BILL_FIELDS, CONF_ACCOUNTS, DOMAIN, HISTORICAL_FIELDS


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create current-month + historical sensors per account number."""
    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    accounts: list[str] = list(entry.data[CONF_ACCOUNTS])

    entities: list[SensorEntity] = []
    for account in accounts:
        # 设备名用地址(最直观), 回退到户号. 数据在 __init__.py 的
        # async_config_entry_first_refresh() 之后已可用.
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

        # 1. 当月传感器: 所有字段
        for key in BILL_FIELDS:
            entities.append(
                JaswjtSensor(coordinator, entry.entry_id, account, key, device_info)
            )

        # 2. 历史传感器: 核心指标 x 每个月份
        # bills[0] 是最新月, 已被上面的当月传感器覆盖, 所以从 bills[1] 开始
        for bill in bills[1:]:
            for key in HISTORICAL_FIELDS:
                entities.append(
                    JaswjtHistoricalSensor(
                        coordinator, entry.entry_id, account, key, bill.month,
                        device_info,
                    )
                )

    async_add_entities(entities)


class JaswjtSensor(CoordinatorEntity, SensorEntity):
    """A single water-bill field exposed as a sensor (latest month only).

    必须同时继承 SensorEntity: 否则平台读取的是 Entity.state (返回 None
    -> "unknown"), 我们自己写的 native_value 属性不会被调用.
    binary_sensor.py 里继承 BinarySensorEntity 是正确的写法, 此处对齐.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry_id: str,
        account: str,
        key: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._account = account
        self._key = key
        self._attr_device_info = device_info
        self._attr_unique_id = f"{entry_id}:{account}:{key}"
        # 直接用 _attr_name 而不是 translation_key: 后者要求
        # strings.json 里有完全对应的 entity 翻译条目, 否则 HA 会告警。
        self._attr_name = BILL_FIELDS[key].get("name") or key

        spec = BILL_FIELDS[key]
        unit = spec.get("unit")
        if unit:
            self._attr_native_unit_of_measure = unit
            if unit == "吨":
                self._attr_device_class = SensorDeviceClass.VOLUME
            # 货币字段有意不设 MONETARY: HA 的 MONETARY 要求最小货币单位(分),
            # 而该 API 返回的是元。设了会导致 HA 校验报错, 因此只保留单位。

    @property
    def _latest(self) -> BillRecord | None:
        """Newest bill row for this account (the API returns newest-first)."""
        bills = self.coordinator.data.get(self._account, [])
        return bills[0] if bills else None

    @property
    def native_value(self):
        rec = self._latest
        if rec is None:
            return None
        return rec.field(self._key)

    @property
    def last_update_time(self):
        rec = self._latest
        if rec is None:
            return None
        return month_to_dt(rec.month)

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
        }


class JaswjtHistoricalSensor(CoordinatorEntity, SensorEntity):
    """One historical (past month) water-bill field sensor.

    unique_id 包含月份, 所以同一个月份永远对应同一个实体, HA recorder 会把
    它的每次 state 变化持久化到 SQLite。新月份到达时, 对应的旧实体 state 不变
    (历史数据不会倒退), 新月份会新增一个实体。
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry_id: str,
        account: str,
        key: str,
        month: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._account = account
        self._key = key
        self._month = month
        self._attr_device_info = device_info
        # unique_id 含月份: 同一月对应同一实体, 不同月是不同实体
        self._attr_unique_id = f"{entry_id}:{account}:{month}:{key}"
        # 名称带月份后缀, 在 HA UI 里一眼能分辨是哪个月的
        base_name = BILL_FIELDS[key].get("name") or key
        self._attr_name = f"{base_name} {self._month_label()}"

        unit = BILL_FIELDS[key].get("unit")
        if unit:
            self._attr_native_unit_of_measure = unit
            if unit == "吨":
                self._attr_device_class = SensorDeviceClass.VOLUME

    def _month_label(self) -> str:
        """202606 -> 2026年06月, 用于实体名称后缀。"""
        if len(self._month) == 6 and self._month.isdigit():
            return f"{self._month[:4]}年{self._month[4:]}月"
        return self._month

    @property
    def _record(self) -> BillRecord | None:
        """Find the bill row matching this sensor's target month."""
        bills = self.coordinator.data.get(self._account, [])
        for bill in bills:
            if bill.month == self._month:
                return bill
        return None

    @property
    def native_value(self):
        rec = self._record
        if rec is None:
            return None
        return rec.field(self._key)

    @property
    def last_update_time(self):
        rec = self._record
        if rec is None:
            return None
        return month_to_dt(rec.month)

    @property
    def extra_state_attributes(self) -> dict:
        rec = self._record
        if rec is None:
            return {}
        return {
            "户号": rec.account,
            "户名": rec.owner,
            "地址": rec.address,
            "月份": rec.month_label,
        }
