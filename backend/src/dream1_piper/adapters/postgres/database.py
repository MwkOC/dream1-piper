from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


class Database:
    def __init__(self, url, settings=None):
        options = dict(pool_size=5, max_overflow=5, pool_timeout=2,
                       pool_recycle=1800, pool_pre_ping=True, pool_use_lifo=True,
                       hide_parameters=True,
                       connect_args={"timeout": 5, "command_timeout": 10,
                                     "server_settings": {
                                         "application_name": "dream1-piper",
                                         "statement_timeout": "5000",
                                         "lock_timeout": "2000",
                                         "idle_in_transaction_session_timeout": "30000"}})
        if settings:
            for key in ("pool_size", "max_overflow", "pool_timeout", "pool_recycle"):
                options[key] = getattr(settings, "database_" + key)
        self.engine = create_async_engine(url, **options)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def check(self):
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def close(self):
        await self.engine.dispose()
