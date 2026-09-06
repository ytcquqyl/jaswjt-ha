"""Constants for the 吉安水务 (Ji'an Water Service) integration."""

from __future__ import annotations

DOMAIN = "jaswjt"

CONF_SESSION_ID = "session_id"
CONF_ACCOUNTS = "accounts"

DEFAULT_SCAN_INTERVAL = 900

BASE_URL = "http://www.jaswjt.com/WeChatNewsJAS"
BILL_URL = f"{BASE_URL}/plugins/wechat.action?method=queryBill&huhao={{account}}"

# 费用状态代码: "Q" = 未缴, 其余 = 已缴
STATUS_UNPAID = "Q"

USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gemini) Mobile/15E148 MicroMessenger/8.0.28"
)

REQUEST_TIMEOUT = 20

# ---------------------------------------------------------------------------
# 账单字段定义（API 原始中文字段名 -> 展示信息）
# key   = API 返回的 JSON 字段名
# name  = 中文显示名（同时用于 Lovelace 卡片 title）
# unit  = HA 单位（"元"/"吨"），None 表示无单位
# ---------------------------------------------------------------------------
BILL_FIELDS: dict[str, dict[str, str | None]] = {
    "月份": {"name": "月份", "unit": None},
    "户号": {"name": "户号", "unit": None},
    "户名": {"name": "户名", "unit": None},
    "地址": {"name": "地址", "unit": None},
    "水量": {"name": "用水量", "unit": "吨"},
    "本期行至": {"name": "本期抄见", "unit": None},
    "上期行至": {"name": "上期抄见", "unit": None},
    "基本水费": {"name": "基本水费", "unit": "元"},
    "污水处理费": {"name": "污水处理费", "unit": "元"},
    "其他费用": {"name": "其他费用", "unit": "元"},
    "垃圾费": {"name": "垃圾费", "unit": "元"},
    "水费": {"name": "水费", "unit": "元"},
    "滞纳金": {"name": "滞纳金", "unit": "元"},
    "费用合计": {"name": "费用合计", "unit": "元"},
    "费用状态": {"name": "费用状态", "unit": None},
    "余额": {"name": "余额", "unit": "元"},
}

# 每个户号生成的核心传感器（按展示优先级排序，前端可取前 N 个）
CORE_FIELDS = ["费用合计", "水量", "本月费用状态", "余额"]

# ---------------------------------------------------------------------------
# 历史数据字段：这些字段会为 API 返回的每一条账单记录（每个月）生成一个
# 独立 sensor。HA recorder 会自动把每次 state 变化写入 SQLite，实现持久化。
# 只选最核心的 2 个指标 —— 字段越多实体越碎, 查询时反而难用。
# 户号/户名/地址/月份是静态元数据, 已通过 attributes 携带, 不需按月生成。
# ---------------------------------------------------------------------------
HISTORICAL_FIELDS: list[str] = ["水量", "费用合计"]
