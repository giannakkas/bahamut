import redis.asyncio as aioredis
from bahamut.config import get_settings
import json
from datetime import datetime, timezone


class RedisManager:
    def __init__(self):
        self.redis = None

    async def connect(self):
        settings = get_settings()
        self.redis = await aioredis.from_url(
            settings.redis_url, decode_responses=True, max_connections=20
        )

    async def disconnect(self):
        if self.redis:
            await self.redis.close()

    async def publish(self, channel: str, data: dict):
        if self.redis:
            payload = json.dumps({
                **data,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            await self.redis.publish(channel, payload)

    async def get(self, key: str):
        if self.redis:
            return await self.redis.get(key)
        return None

    async def set(self, key: str, value: str, ex: int = None):
        if self.redis:
            await self.redis.set(key, value, ex=ex)

    async def get_json(self, key: str):
        val = await self.get(key)
        return json.loads(val) if val else None

    async def set_json(self, key: str, data: dict, ex: int = None):
        await self.set(key, json.dumps(data), ex=ex)


redis_manager = RedisManager()
