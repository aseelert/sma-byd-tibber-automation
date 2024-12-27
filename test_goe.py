import asyncio
import aiohttp
import logging
from datetime import datetime
from dotenv import load_dotenv
import os

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def test_goe_endpoints():
    """Test both controller and charger endpoints"""
    load_dotenv()

    # Test endpoints
    endpoints = {
        'controller': f"http://{os.getenv('GOE_CONTROLLER_HOST')}/api/status",
        'charger': f"http://{os.getenv('GOE_HOST')}/api/status"
    }

    async with aiohttp.ClientSession() as session:
        for name, url in endpoints.items():
            print(f"\nTesting {name} at {url}")
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        print(f"\n{name.title()} Response:")
                        print(f"Status: {response.status}")
                        print("Data:")
                        for key, value in data.items():
                            print(f"{key}: {value}")
                    else:
                        print(f"Error: Status {response.status}")
            except Exception as e:
                print(f"Error accessing {name}: {e}")

if __name__ == "__main__":
    asyncio.run(test_goe_endpoints())