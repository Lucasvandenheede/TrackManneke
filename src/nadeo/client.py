import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncContextManager, Optional
import aiohttp
from .auth import NadeoAuth

logger = logging.getLogger(__name__)

class NadeoClient:
    def __init__(self, auth: NadeoAuth, user_agent: str):
        self.auth = auth
        self.user_agent = user_agent
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None
        await self.auth.close()

    @asynccontextmanager
    async def _request(
        self,
        method: str,
        url: str,
        region: str = "NadeoLiveServices",
        **kwargs,
    ):
        session = await self.get_session()

        try:
            token = await self.auth.get_nadeo_token(region)
            headers = kwargs.pop("headers", {})
            headers["Authorization"] = f"nadeo_v1 t={token}"
            headers["User-Agent"] = self.user_agent

            logger.debug(f"{method.upper()} {url}")

            async with session.request(method, url, headers=headers, **kwargs) as resp:
                if resp.status == 401:
                    logger.warning("Got 401 Unauthorized, invalidating cached token and retrying...")
                    self.auth.invalidate_token(region)
                    token = await self.auth.get_nadeo_token(region)
                    headers["Authorization"] = f"nadeo_v1 t={token}"

                    async with session.request(
                        method, url, headers=headers, **kwargs
                    ) as retry_resp:
                        yield retry_resp
                else:
                    yield resp
        except asyncio.TimeoutError as e:
            logger.error(f"Request timeout for {method} {url}: {e}")
            raise
        except Exception as e:
            logger.warning(f"Request failed for {method} {url}: {e}")
            raise

    def get(
        self,
        url: str,
        region: str = "NadeoLiveServices",
        **kwargs,
    ) -> AsyncContextManager[aiohttp.ClientResponse]:
        return self._request("GET", url, region, **kwargs)

    def post(
        self,
        url: str,
        region: str = "NadeoLiveServices",
        **kwargs,
    ) -> AsyncContextManager[aiohttp.ClientResponse]:
        return self._request("POST", url, region, **kwargs)

    def put(
        self,
        url: str,
        region: str = "NadeoLiveServices",
        **kwargs,
    ) -> AsyncContextManager[aiohttp.ClientResponse]:
        return self._request("PUT", url, region, **kwargs)

    def delete(
        self,
        url: str,
        region: str = "NadeoLiveServices",
        **kwargs,
    ) -> AsyncContextManager[aiohttp.ClientResponse]:
        return self._request("DELETE", url, region, **kwargs)