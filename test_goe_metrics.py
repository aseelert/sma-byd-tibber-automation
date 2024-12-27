import asyncio
import aiohttp
import logging
from datetime import datetime
from dotenv import load_dotenv
import os
import pandas as pd

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def get_charger_metrics():
    """Get key metrics from the charger"""
    load_dotenv()
    url = f"http://{os.getenv('GOE_HOST')}/api/status"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()

                    # Extract key metrics
                    metrics = {
                        'timestamp': datetime.now(),
                        'car_status': data.get('car'),
                        'charging_allowed': bool(data.get('alw', 0)),
                        'current_power_w': float(data.get('nrg', [0]*12)[11]) / 10.0,
                        'session_energy_kwh': float(data.get('dws', 0)) / 360000.0,
                        'total_energy_kwh': float(data.get('eto', 0)) / 10.0,
                        'charging_current_a': int(data.get('amp', 0)),
                        'max_current_a': int(data.get('ama', 0)),
                        'temperature_c': float(data.get('tmp', 0))
                    }

                    # Create DataFrame
                    df = pd.DataFrame([metrics])
                    return df

        except Exception as e:
            logger.error(f"Error getting charger metrics: {e}")
            return None

async def get_controller_metrics():
    """Get key metrics from the controller"""
    load_dotenv()
    url = f"http://{os.getenv('GOE_CONTROLLER_HOST')}/api/status"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()

                    # Extract key metrics (adjust based on actual response)
                    metrics = {
                        'timestamp': datetime.now(),
                        'total_power_w': data.get('total_power', 0),
                        'active_sessions': data.get('active_sessions', 0),
                        'available_chargers': data.get('available_chargers', 0)
                    }

                    # Create DataFrame
                    df = pd.DataFrame([metrics])
                    return df

        except Exception as e:
            logger.error(f"Error getting controller metrics: {e}")
            return None

async def main():
    # Get metrics
    charger_df = await get_charger_metrics()
    controller_df = await get_controller_metrics()

    # Print results
    if charger_df is not None:
        print("\nCharger Metrics:")
        print(charger_df.to_string())

    if controller_df is not None:
        print("\nController Metrics:")
        print(controller_df.to_string())

    # Optional: Save to CSV
    if charger_df is not None:
        charger_df.to_csv('charger_metrics.csv', mode='a', header=not os.path.exists('charger_metrics.csv'))
    if controller_df is not None:
        controller_df.to_csv('controller_metrics.csv', mode='a', header=not os.path.exists('controller_metrics.csv'))

if __name__ == "__main__":
    asyncio.run(main())