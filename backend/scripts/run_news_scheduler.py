import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

sys.path.append(os.getcwd())

from backend.scheduler import start_scheduler, shutdown_scheduler

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('news_scheduler')


async def main():
    logger.info('Starting news scheduler service...')
    start_scheduler()
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        shutdown_scheduler()
        logger.info('News scheduler service stopped.')


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
