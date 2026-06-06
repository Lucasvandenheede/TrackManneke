import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from urllib.parse import urlencode

import aiohttp

logger = logging.getLogger(__name__)


class OAuthClient:
    """Trackmania OAuth client for machine-to-machine authentication.

    Uses the Client Credentials OAuth flow to get generic tokens for accessing
    public API resources like display name lookups.

    Ref: https://doc.trackmania.com/web/web-services/auth/
    """

    OAUTH_TOKEN_URL = "https://api.trackmania.com/api/access_token"
    DISPLAY_NAMES_URL = "https://api.trackmania.com/api/display-names"

    def __init__(self, client_id: str, client_secret: str):
        """Initialize OAuthClient with OAuth credentials.

        Args:
            client_id: OAuth application ID (from api.trackmania.com)
            client_secret: OAuth application secret
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp ClientSession."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the session."""
        if self._session:
            await self._session.close()
            self._session = None

    async def _fetch_token(self) -> Dict[str, Any]:
        """Fetch a new OAuth access token using Client Credentials flow.

        Returns:
            Dict with access_token and expires_at

        Raises:
            Exception: If token request fails
        """
        logger.info("Fetching OAuth token via Client Credentials flow...")
        session = await self.get_session()

        try:
            params = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }

            async with session.post(
                self.OAUTH_TOKEN_URL,
                data=params,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(
                        f"OAuth token request failed with status {resp.status}: {error_text}"
                    )
                    raise Exception(f"OAuth token request failed: {resp.status}")

                data = await resp.json()
                access_token = data["access_token"]
                expires_in = data["expires_in"]
                expires_at = datetime.now() + timedelta(seconds=expires_in)

                logger.info(f"Successfully obtained OAuth token, expires at {expires_at}")

                return {
                    "access_token": access_token,
                    "expires_at": expires_at,
                }
        except asyncio.TimeoutError:
            logger.error("Timeout while fetching OAuth token")
            raise
        except Exception as e:
            logger.error(f"Error getting OAuth token: {e}")
            raise

    async def get_access_token(self) -> str:
        """Get valid OAuth access token with automatic refresh.

        Returns:
            Valid OAuth access token
        """
        now = datetime.now()

        if self._access_token and self._token_expires_at:
            time_until_expiry = (self._token_expires_at - now).total_seconds() / 60

            if time_until_expiry > 5:
                logger.debug(f"Using cached OAuth token (expires in {time_until_expiry:.1f} min)")
                return self._access_token

        token_data = await self._fetch_token()
        self._access_token = token_data["access_token"]
        self._token_expires_at = token_data["expires_at"]
        return self._access_token

    async def get_display_names(self, account_ids: list) -> Dict[str, str]:
        """Get display names for account IDs.

        Args:
            account_ids: List of account ID UUIDs (max 50)

        Returns:
            Dict mapping account_id -> display_name

        Raises:
            Exception: If request fails
        """
        if not account_ids:
            return {}

        if len(account_ids) > 50:
            raise ValueError("Maximum 50 account IDs allowed per request")

        token = await self.get_access_token()
        session = await self.get_session()

        try:
            # Build query parameters: accountId[]=id1&accountId[]=id2&...
            params = {"accountId[]": account_ids}
            query_string = urlencode(params, doseq=True)

            async with session.get(
                f"{self.DISPLAY_NAMES_URL}?{query_string}",
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(
                        f"Display names request failed with status {resp.status}: {error_text}"
                    )
                    raise Exception(f"Display names request failed: {resp.status}")

                data = await resp.json()
                logger.debug(f"Retrieved display names for {len(data)} accounts")
                return data
        except asyncio.TimeoutError:
            logger.error("Timeout while fetching display names")
            raise
        except Exception as e:
            logger.error(f"Error getting display names: {e}")
            raise
