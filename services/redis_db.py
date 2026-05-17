from redis.asyncio import Redis


class RedisCategoryService:
    def __init__(self, redis_url: str, categories_key: str) -> None:
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.categories_key = categories_key

    async def close(self) -> None:
        await self.redis.aclose()

    async def get_categories(self) -> set[str]:
        values = await self.redis.smembers(self.categories_key)
        return {value for value in values if value}

    async def add_category(self, category: str) -> None:
        await self.redis.sadd(self.categories_key, category)

    async def replace_categories(self, categories: set[str]) -> None:
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.delete(self.categories_key)
            if categories:
                pipe.sadd(self.categories_key, *categories)
            await pipe.execute()

    async def clear_categories(self) -> None:
        await self.redis.delete(self.categories_key)
