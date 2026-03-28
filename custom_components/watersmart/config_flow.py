"""Config flow for WaterSmart integration."""

from asyncio import timeout
import logging
from typing import Any

from aiohttp import ClientError
from aiohttp.client_exceptions import ClientConnectorError
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .client import AuthenticationError, TwoFactorAuthRequiredError, WaterSmartClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_2FA_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("code"): str,
    }
)


class WaterSmartConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a config flow for WaterSmart."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._user_input: dict[str, Any] = {}
        self._client: WaterSmartClient | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step.

        Returns:
            The config flow result.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            self._user_input = user_input
            session = async_get_clientsession(self.hass)
            self._client = WaterSmartClient(
                user_input[CONF_HOST],
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                session=session,
            )

            try:
                async with timeout(30):
                    account_number = await self._client.async_get_account_number()
            except (ClientConnectorError, TimeoutError, ClientError):
                errors["base"] = "cannot_connect"
            except TwoFactorAuthRequiredError:
                # 2FA is required, proceed to 2FA step
                return await self.async_step_2fa()
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                if not account_number:
                    errors["base"] = "invalid_auth"
                else:
                    return self.async_create_entry(
                        title=f"{user_input[CONF_HOST]} ({user_input[CONF_USERNAME]})",
                        data=user_input,
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "example_host": "bendoregon",
                "example_url": "https://bendoregon.watersmart.com/",
            },
        )

    async def async_step_2fa(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the 2FA verification step.

        Returns:
            The config flow result.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            if self._client is None:
                # Client was lost, restart flow
                return await self.async_step_user()

            try:
                async with timeout(30):
                    await self._client.async_submit_2fa_code(user_input["code"])
                    account_number = await self._client.async_get_account_number()
            except (ClientConnectorError, TimeoutError, ClientError):
                errors["base"] = "cannot_connect"
            except AuthenticationError:
                errors["base"] = "invalid_2fa_code"
            except Exception:
                _LOGGER.exception("Unexpected exception during 2FA")
                errors["base"] = "unknown"
            else:
                if not account_number:
                    errors["base"] = "invalid_auth"
                else:
                    # Save cookies for bypassing 2FA on restart
                    entry_data = {
                        **self._user_input,
                        "cookies": self._client.get_cookies(),
                    }
                    return self.async_create_entry(
                        title=f"{self._user_input[CONF_HOST]} ({self._user_input[CONF_USERNAME]})",
                        data=entry_data,
                    )

        return self.async_show_form(
            step_id="2fa",
            data_schema=STEP_2FA_DATA_SCHEMA,
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
