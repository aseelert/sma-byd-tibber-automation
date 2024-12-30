import asyncio
import logging
import json
import aiohttp
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from pymodbus.client import ModbusTcpClient
from dotenv import load_dotenv
import os

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BatteryMode(Enum):
    NORMAL = 0      # Normal operation
    PAUSE = 1       # Pause charging/discharging
    GRID_CHARGE = 2 # Force charge from grid

@dataclass
class BatteryStatus:
    soc: float              # State of charge (%)
    power: int              # Current power (W)
    mode: BatteryMode       # Current operation mode
    target_power: int       # Target charging power (W)
    is_charging: bool       # True if currently charging
    temperature: float      # Battery temperature
    cycles: int             # Charge cycles

@dataclass
class SystemStatus:
    battery: BatteryStatus
    car_charging: bool
    pv_power: float
    grid_power: float
    home_consumption: float
    current_price: float
    next_cheap_window: Optional[datetime]

class SMAModbus:
    def __init__(self):
        load_dotenv()
        self.host = os.getenv('SMA_MODBUS_HOST', '192.168.178.57')
        self.port = int(os.getenv('SMA_MODBUS_PORT', '502'))
        self.unit_id = int(os.getenv('SMA_MODBUS_UNIT_ID', '3'))
        self.client = None

    async def connect(self):
        try:
            self.client = ModbusTcpClient(self.host, port=self.port)
            return self.client.connect()
        except Exception as e:
            logger.error(f"Error connecting to SMA: {e}")
            return False

    async def read_register(self, address):
        try:
            if not self.client or not self.client.connected:
                await self.connect()
            result = self.client.read_holding_registers(address, 1, unit=self.unit_id)
            if result.isError():
                raise Exception(f"Modbus error reading register {address}")
            return result.registers[0]
        except Exception as e:
            logger.error(f"Error reading register {address}: {e}")
            return None

    async def write_register(self, address, value):
        try:
            if not self.client or not self.client.connected:
                await self.connect()
            result = self.client.write_register(address, value, unit=self.unit_id)
            if result.isError():
                raise Exception(f"Modbus error writing register {address}")
            return True
        except Exception as e:
            logger.error(f"Error writing register {address}: {e}")
            return False

class TibberClient:
    def __init__(self):
        load_dotenv()
        self.token = os.getenv('TIBBER_API_KEY')
        self.url = "https://api.tibber.com/v1-beta/gql"

    async def get_current_price(self):
        """Get current Tibber price"""
        prices = await self.get_price_range(0, 1)
        return prices[0]['total'] if prices else None

    async def get_price_range(self, hours_past=12, hours_future=24):
        """Get price information for a range of hours"""
        query = """
        {
          viewer {
            homes {
              currentSubscription{
                priceInfo{
                  current {
                    total
                    startsAt
                  }
                  today {
                    total
                    startsAt
                    level
                  }
                  tomorrow {
                    total
                    startsAt
                    level
                  }
                }
              }
            }
          }
        }
        """

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.url,
                    json={'query': query},
                    headers={"Authorization": f"Bearer {self.token}"}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        price_info = data['data']['viewer']['homes'][0]['currentSubscription']['priceInfo']

                        # Combine today and tomorrow
                        prices = []
                        if price_info.get('today'):
                            prices.extend(price_info['today'])
                        if price_info.get('tomorrow'):
                            prices.extend(price_info['tomorrow'])

                        return prices
        except Exception as e:
            logger.error(f"Error fetching Tibber prices: {e}")
            return []

class GoeCharger:
    def __init__(self):
        load_dotenv()
        self.host = os.getenv('GOE_HOST', '192.168.178.59')

    async def get_status(self):
        """Get charger status"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://{self.host}/api/status") as response:
                    if response.status == 200:
                        data = await response.json()
                        return {'is_charging': data.get('car', 0) == 2}
                    return None
        except Exception as e:
            logger.error(f"Error getting GO-E status: {e}")
            return None

class BatteryOptimizer:
    def __init__(self):
        # Initialize components
        self.sma = SMAModbus()
        self.goe = GoeCharger()
        self.tibber = TibberClient()

        # Configuration
        self.price_threshold_very_cheap = 0.10  # €/kWh
        self.price_threshold_cheap = 0.15
        self.price_threshold_normal = 0.20
        self.min_charging_time = 2  # hours

        # Battery settings
        self.max_capacity = 5000  # 5kWh battery
        self.min_soc = 20        # Minimum SoC for backup
        self.max_soc = 95        # Maximum SoC to preserve battery life
        self.optimal_soc = 80    # Optimal SoC for daily operation

        # Logging setup
        self.log_dir = Path('logs')
        self.log_dir.mkdir(exist_ok=True)
        self.state_history = []

    # ... [Previous methods from SmartEnergyController remain the same] ...

async def main():
    optimizer = BatteryOptimizer()

    # Initial connection
    await optimizer.sma.connect()

    print(f"\nBattery Optimization System")
    print("=" * 50)

    while True:
        try:
            status = await optimizer.get_system_status()
            if status:
                await optimizer.optimize_charging(status)
                await optimizer.log_system_state(status)

                # Print current status
                print(f"\nSystem Status at {datetime.now().strftime('%H:%M:%S')}:")
                print(f"Battery: {status.battery.soc}% | {status.battery.power}W")
                print(f"Price: {status.current_price:.3f}€/kWh")
                print(f"Mode: {status.battery.mode.name}")
                if status.car_charging:
                    print("Car is charging - Battery paused")
                print("-" * 50)

        except Exception as e:
            logger.error(f"Main loop error: {e}")

        await asyncio.sleep(300)  # Run every 5 minutes

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")