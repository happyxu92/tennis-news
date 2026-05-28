import asyncio

from app.main import run_async

if __name__ == "__main__":
    asyncio.run(run_async("init-db"))
