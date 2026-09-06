"""Async client for the 吉安水务 water-bill web API.

The water utility (www.jaswjt.com/WeChatNewsJAS) is a servlet-based web app
originally built for a WeChat mini-program.  Auth is a single ``JSESSIONID``
cookie that is created when the user opens the mini-program (WeChat OAuth).

The bill endpoint returns an HTML page.  The real data is injected server-side
into a JS variable::

    var waterfeeinfo = jQuery.parseJSON('{...}');

The server leaves the template empty when the session is invalid, so an empty
payload is our signal that the session has expired.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aiohttp

from .const import (
    BILL_URL,
    REQUEST_TIMEOUT,
    STATUS_UNPAID,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)


class JaswjtError(Exception):
    """Base error for this integration."""


class SessionExpired(JaswjtError):
    """The JSESSIONID is no longer valid (empty payload returned)."""


class NoAccounts(JaswjtError):
    """No account numbers were configured."""


@dataclass(slots=True)
class BillRecord:
    """One monthly water bill."""

    month: str  # YYYYMM, e.g. "202608"
    account: str
    owner: str
    address: str
    volume: float  # 吨 (tonnes)
    current_meter: float  # 本期行至 - 本期抄见
    previous_meter: float | None  # 上期行至
    basic_fee: float
    sewage_fee: float
    other_fee: float
    garbage_fee: float
    water_fee: float
    late_fee: float
    total_fee: float
    status_code: str  # "Q" = unpaid, anything else = paid
    balance: float

    @property
    def paid(self) -> bool:
        return self.status_code != STATUS_UNPAID

    @property
    def month_label(self) -> str:
        """202608 -> 2026年08月."""
        if len(self.month) == 6 and self.month.isdigit():
            return f"{self.month[:4]}年{self.month[4:]}月"
        return self.month

    def field(self, key: str) -> Any:
        """Return a raw bill value by its Chinese field name.

        Returns a human-readable string for 费用状态 (已缴/未缴) and falls back
        to ``None`` for unknown keys instead of raising - the sensor platform
        treats ``None`` as "no data", which is the right UI behaviour.
        """
        if key == "费用状态":
            return "已缴" if self.paid else "未缴"
        if key == "月份":
            return self.month_label
        if key == "户号":
            return self.account
        if key == "户名":
            return self.owner or None
        if key == "地址":
            return self.address or None
        mapping = {
            "水量": self.volume,
            "本期行至": self.current_meter,
            "上期行至": self.previous_meter,
            "基本水费": self.basic_fee,
            "污水处理费": self.sewage_fee,
            "其他费用": self.other_fee,
            "垃圾费": self.garbage_fee,
            "水费": self.water_fee,
            "滞纳金": self.late_fee,
            "费用合计": self.total_fee,
            "余额": self.balance,
        }
        return mapping.get(key)


class JaswjtClient:
    """Talks to the 吉安水务 web API."""

    def __init__(self, session_id: str, accounts: list[str]) -> None:
        if not session_id:
            raise NoAccounts("JSESSIONID is required")
        if not accounts:
            raise NoAccounts("至少需要一个户号")
        self._session_id = session_id.strip()
        self._accounts = [a.strip() for a in accounts if a.strip()]
        self._timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

    async def fetch_bills(self) -> dict[str, list[BillRecord]]:
        """Return ``{account: [BillRecord, ...]}`` sorted newest-first."""
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            results: dict[str, list[BillRecord]] = {}
            for account in self._accounts:
                results[account] = await self._fetch_account(session, account)
            return results

    async def _fetch_account(self, session: aiohttp.ClientSession, account: str) -> list[BillRecord]:
        url = BILL_URL.format(account=account)
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": "http://www.jaswjt.com/WeChatNewsJAS/",
            "Cookie": f"JSESSIONID={self._session_id}",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        _LOGGER.debug("Fetching water bill for account %s", account)
        async with session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            html = await resp.text(encoding="utf-8", errors="replace")

        payload = extract_waterfeeinfo(html)
        if payload is None:
            raise SessionExpired(
                f"户号 {account} 未返回数据，JSESSIONID 可能已过期，"
                "请重新在微信中打开小程序后更新"
            )
        return [parse_record(raw, account) for raw in payload]

    async def close(self) -> None:  # pragma: no cover - defensive
        pass


def extract_waterfeeinfo(html: str) -> list[Any] | None:
    """Pull the ``data`` array out of ``var waterfeeinfo = jQuery.parseJSON('...')``.

    The payload is a JS single-quoted string but its content is JSON.  We locate
    the opening brace and balance braces while respecting JSON string escaping,
    so embedded ``'`` characters cannot truncate the match.  Returns ``None``
    when the server left the template empty (invalid session).
    """
    marker = "jQuery.parseJSON('"
    start = html.find(marker)
    if start == -1:
        return None
    cursor = start + len(marker)

    # skip to the first "{"
    while cursor < len(html) and html[cursor] != "{":
        cursor += 1
    if cursor >= len(html):
        return None

    depth = 0
    in_string = False
    escaped = False
    for i in range(cursor, len(html)):
        ch = html[i]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                raw = html[cursor : i + 1]
                try:
                    import json

                    data = json.loads(raw)
                    return data.get("data")
                except (ValueError, TypeError):
                    return None
    return None


def _num(value: Any) -> float:
    """Coerce a bill field to float, tolerating None / '' / garbage."""
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def parse_record(raw: dict[str, Any], account: str) -> BillRecord:
    """Build a BillRecord from a raw API row.  All keys are Chinese field names."""
    month = str(raw.get("月份") or "").strip()
    return BillRecord(
        month=month,
        account=str(raw.get("户号") or account).strip(),
        owner=str(raw.get("户名") or "").strip(),
        address=str(raw.get("地址") or "").strip(),
        volume=_num(raw.get("水量")),
        current_meter=_num(raw.get("本期行至")),
        previous_meter=_num(raw.get("上期行至")) or None,
        basic_fee=_num(raw.get("基本水费")),
        sewage_fee=_num(raw.get("污水处理费")),
        other_fee=_num(raw.get("其他费用")),
        garbage_fee=_num(raw.get("垃圾费")),
        water_fee=_num(raw.get("水费")),
        late_fee=_num(raw.get("滞纳金")),
        total_fee=_num(raw.get("费用合计")),
        status_code=str(raw.get("费用状态") or "").strip(),
        balance=_num(raw.get("余额")),
    )


def month_to_dt(month: str) -> datetime | None:
    """202608 -> 2026-08-01.  Used for sensor last_updated semantics."""
    if len(month) != 6 or not month.isdigit():
        return None
    try:
        return datetime.strptime(month, "%Y%m")
    except ValueError:
        return None
