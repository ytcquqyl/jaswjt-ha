"""Config flow for the 吉安水务 (Ji'an Water Service) integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .client import JaswjtClient, NoAccounts, SessionExpired
from .const import CONF_ACCOUNTS, CONF_SESSION_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

TITLE_PLACEHOLDER = "吉安水务"

USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SESSION_ID): str,
        vol.Required(CONF_ACCOUNTS): str,
    }
)


class JaswjtConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for 吉安水务."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """First step: ask for the session id and account numbers."""
        errors: dict[str, str] = {}

        if user_input is not None:
            session_id = user_input[CONF_SESSION_ID].strip()
            accounts = _parse_accounts(user_input[CONF_ACCOUNTS])

            if not session_id:
                errors[CONF_SESSION_ID] = "请填写 JSESSIONID"
            if not accounts:
                errors[CONF_ACCOUNTS] = "请至少填写一个户号"

            if not errors:
                await self.async_set_unique_id(session_id)
                self._abort_if_unique_id_configured()

                # Validate before creating the entry so the user never gets a
                # broken integration.  The API returns an empty template when
                # the session has expired.
                try:
                    client = JaswjtClient(session_id, accounts)
                    bills = await client.fetch_bills()
                except SessionExpired:
                    errors["base"] = (
                        "JSESSIONID 无效或已过期。请在微信中重新打开"
                        "吉安水务小程序，然后重新复制 JSESSIONID。"
                    )
                except NoAccounts as exc:
                    errors["base"] = str(exc)
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.warning("吉安水务连接失败: %s", exc)
                    errors["base"] = f"连接失败: {exc}"

            if not errors:
                return self.async_create_entry(
                    title=f"吉安水务 {accounts[0]}",
                    data={CONF_SESSION_ID: session_id, CONF_ACCOUNTS: accounts},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=USER_DATA_SCHEMA,
            errors=errors,
        )


class JaswjtOptionsFlow(OptionsFlow):
    """Allow changing the session id / accounts without re-adding."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit session id and accounts."""
        errors: dict[str, str] = {}
        entry = self._get_entry_flow().config_entry
        current = entry.data

        if user_input is not None:
            session_id = user_input[CONF_SESSION_ID].strip()
            accounts = _parse_accounts(user_input[CONF_ACCOUNTS])

            if not session_id:
                errors[CONF_SESSION_ID] = "请填写 JSESSIONID"
            if not accounts:
                errors[CONF_ACCOUNTS] = "请至少填写一个户号"

            if not errors:
                try:
                    client = JaswjtClient(session_id, accounts)
                    await client.fetch_bills()
                except SessionExpired:
                    errors["base"] = "JSESSIONID 无效或已过期，请重新获取。"
                except Exception as exc:  # noqa: BLE001
                    errors["base"] = f"连接失败: {exc}"

            if not errors:
                return self.async_create_entry(
                    title="",
                    data={CONF_SESSION_ID: session_id, CONF_ACCOUNTS: accounts},
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SESSION_ID, default=current.get(CONF_SESSION_ID, "")
                ): str,
                vol.Required(
                    CONF_ACCOUNTS,
                    default=", ".join(current.get(CONF_ACCOUNTS, [])),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)


def _parse_accounts(raw: str) -> list[str]:
    """Split a free-form account field on commas, spaces, and CJK punctuation."""
    import re

    parts = re.split(r"[,\s，、;；/]+", raw or "")
    return [p.strip() for p in parts if p.strip()]
