import asyncio
import base64
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any

import aiohttp

logger = logging.getLogger(__name__)


class NadeoAuth:
    NADEO_TOKEN_URL = "https://prod.trackmania.core.nadeo.online/v2/authentication/token/basic"
    NADEO_REFRESH_URL = "https://prod.trackmania.core.nadeo.online/v2/authentication/token/refresh"

    def __init__(self, service_account_login: str, service_account_password: str):
        self.login = service_account_login
        self.password = service_account_password
        self._nadeo_tokens: Dict[str, Dict[str, Any]] = {}
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    @staticmethod
    def _decode_jwt_exp(token: str) -> datetime:
        try:
            parts = token.split(".")
            if len(parts) != 3:
                raise ValueError("Invalid JWT format: expected 3 parts")

            payload = parts[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += "=" * padding

            decoded = base64.urlsafe_b64decode(payload)
            payload_data = json.loads(decoded)

            exp_timestamp = payload_data.get("exp")
            if not exp_timestamp:
                raise ValueError("JWT missing 'exp' claim")

            return datetime.fromtimestamp(exp_timestamp)
        except Exception as e:
            logger.error(f"Failed to decode JWT: {e}")
            raise

    def _get_basic_auth_header(self) -> str:
        credentials = f"{self.login}:{self.password}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"

    async def _fetch_token(self, audience: str = "NadeoLiveServices") -> Dict[str, Any]:
        logger.info(f"Fetching new Nadeo token for audience {audience}...")
        session = await self.get_session()

        try:
            async with session.post(
                self.NADEO_TOKEN_URL,
                json={"audience": audience},
                headers={
                    "Authorization": self._get_basic_auth_header(),
                    "Content-Type": "application/json",
                },
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(
                        f"Nadeo token request failed with status {resp.status}: {error_text}"
                    )
                    raise Exception(f"Nadeo token request failed: {resp.status}")

                data = await resp.json()
                access_token = data["accessToken"]
                refresh_token = data.get("refreshToken")
                expires_at = self._decode_jwt_exp(access_token)

                logger.info(
                    f"Successfully obtained Nadeo token for {audience}, "
                    f"expires at {expires_at}"
                )

                return {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": expires_at,
                }
        except asyncio.TimeoutError:
            logger.error(f"Timeout while fetching Nadeo token for {audience}")
            raise
        except Exception as e:
            logger.error(f"Error getting Nadeo token for {audience}: {e}")
            raise

    async def _refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        logger.info("Refreshing Nadeo token...")
        session = await self.get_session()

        try:
            async with session.post(
                self.NADEO_REFRESH_URL,
                headers={
                    "Authorization": f"nadeo_v1 t={refresh_token}",
                    "Content-Type": "application/json",
                },
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(
                        f"Nadeo token refresh failed with status {resp.status}: {error_text}"
                    )
                    raise Exception(f"Nadeo token refresh failed: {resp.status}")

                data = await resp.json()
                access_token = data["accessToken"]
                refresh_token = data.get("refreshToken")
                expires_at = self._decode_jwt_exp(access_token)

                logger.info(f"Successfully refreshed Nadeo token, expires at {expires_at}")

                return {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": expires_at,
                }
        except asyncio.TimeoutError:
            logger.error("Timeout while refreshing Nadeo token")
            raise
        except Exception as e:
            logger.error(f"Error refreshing Nadeo token: {e}")
            raise

    def invalidate_token(self, audience: str) -> None:
        if audience in self._nadeo_tokens:
            logger.info(f"Invalidating cached Nadeo token for {audience}")
            del self._nadeo_tokens[audience]

    async def get_nadeo_token(self, audience: str = "NadeoLiveServices") -> str:
        now = datetime.now()

        if audience in self._nadeo_tokens:
            token_data = self._nadeo_tokens[audience]
            expires_at = token_data["expires_at"]
            time_until_expiry = (expires_at - now).total_seconds() / 60

            if time_until_expiry > 5:
                logger.debug(
                    f"Using cached Nadeo token for {audience} "
                    f"(expires in {time_until_expiry:.1f} min)"
                )
                return token_data["access_token"]
            else:
                logger.info(f"Nadeo token for {audience} expiring soon, refreshing...")

                refresh_token = token_data.get("refresh_token")
                if refresh_token:
                    try:
                        new_token_data = await self._refresh_token(refresh_token)
                        self._nadeo_tokens[audience] = new_token_data
                        return new_token_data["access_token"]
                    except Exception as e:
                        logger.warning(
                            f"Token refresh failed, fetching new token: {e}"
                        )

        token_data = await self._fetch_token(audience)
        self._nadeo_tokens[audience] = token_data
        return token_data["access_token"]
