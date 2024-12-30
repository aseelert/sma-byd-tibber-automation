import asyncio
import logging
import json
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from pymodbus.client import ModbusTcpClient
from dotenv import load_dotenv
import os
from pymodbus.constants import Endian

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BatteryMode(Enum):
    NORMAL = 803      # Normal operation (0x323)
    PAUSE = 802       # Pause charging/discharging (0x322)
    GRID_CHARGE = 802 # Grid charge uses same mode as pause, but with power setting

@dataclass
class BatteryStatus:
    soc: float              # State of charge (%)
    power: int              # Current power (W)
    mode: BatteryMode       # Current operation mode
    target_power: int       # Target charging power (W)
    is_charging: bool       # True if currently charging
    temperature: float      # Battery temperature

class SmartEnergyController:
    def __init__(self):
        load_dotenv()

        # SMA Configuration
        self.sma_host = os.getenv('SMA_MODBUS_HOST', '192.168.178.57')
        self.sma_port = int(os.getenv('SMA_MODBUS_PORT', '502'))
        self.sma_unit_id = int(os.getenv('SMA_MODBUS_UNIT_ID', '3'))
        self.sma_client = None

        # GO-E Configuration
        self.goe_host = os.getenv('GOE_HOST', '192.168.178.59')

        # Tibber Configuration
        self.tibber_token = os.getenv('TIBBER_API_KEY')
        self.tibber_url = "https://api.tibber.com/v1-beta/gql"

        # Battery settings
        self.max_capacity = 5000  # 5kWh battery
        self.min_soc = 20        # Minimum SoC for backup
        self.max_soc = 95        # Maximum SoC to preserve battery life
        self.optimal_soc = 80    # Optimal SoC for daily operation
        self.charge_power = 2500 # Default charge power (W)

        # Price thresholds
        self.price_threshold_very_cheap = 0.10  # €/kWh
        self.price_threshold_cheap = 0.15
        self.price_threshold_normal = 0.20

        # State tracking
        self.state_history: List[Dict] = []
        self.last_mode_change = datetime.now()

        # Create log directory
        self.log_dir = Path('logs')
        self.log_dir.mkdir(exist_ok=True)

        # Updated register addresses from sma_modbus.py
        self.registers = {
            'grid_power': 30865,      # Grid power exchange
            'pv_power': 30775,        # Current power consumption
            'solar_power': 30773,     # Current solar generation power
            'battery_soc': 30845,      # Battery State of Charge in %
            'battery_mode': 40151,    # Battery operation mode register
            'battery_power': 40149,   # Battery power control register
        }

    async def connect_sma(self):
        """Connect to SMA inverter"""
        try:
            self.sma_client = ModbusTcpClient(self.sma_host, port=self.sma_port)
            return self.sma_client.connect()
        except Exception as e:
            logger.error(f"Error connecting to SMA: {e}")
            return False

    async def read_sma_register(self, register_addr, count=2):
        """Read register with proper error handling - matching sma_modbus.py"""
        try:
            if not self.sma_client or not self.sma_client.connected:
                await self.connect_sma()

            logger.debug(f"Attempting to read register {register_addr} with count {count}")

            # Try both address variants as in sma_modbus.py
            for base_adjust in [0, -1]:
                address = register_addr + base_adjust
                logger.debug(f"Trying address: {address}")

                result = self.sma_client.read_holding_registers(
                    address=address,
                    count=count,
                    slave=self.sma_unit_id
                )

                if not result:
                    logger.debug(f"No response from register {register_addr} at address {address}")
                    continue

                if result.isError():
                    logger.debug(f"Error reading register {register_addr} at address {address}: {result}")
                    continue

                logger.debug(f"Successfully read register {register_addr} at address {address}: {result.registers}")
                return result.registers

            logger.error(f"Failed to read register {register_addr} with all address variants")
            return None

        except Exception as e:
            logger.error(f"Error reading register {register_addr}: {e}")
            return None

    def decode_s32(self, registers):
        """Decode signed 32-bit integer"""
        try:
            if not registers or len(registers) < 2:
                return 0

            # Combine two 16-bit registers into one 32-bit value
            value = (registers[0] << 16) | registers[1]

            # Handle signed values
            if value & 0x80000000:  # If highest bit is set (negative)
                value = -((~value & 0xFFFFFFFF) + 1)

            return value

        except Exception as e:
            logger.error(f"Error decoding signed 32-bit value: {e}")
            return 0

    def decode_u32(self, registers):
        """Decode unsigned 32-bit integer"""
        try:
            if not registers or len(registers) < 2:
                return 0

            # Combine two 16-bit registers into one 32-bit value
            return (registers[0] << 16) | registers[1]

        except Exception as e:
            logger.error(f"Error decoding unsigned 32-bit value: {e}")
            return 0

    async def get_car_charging_status(self) -> bool:
        """Get GO-E charger status"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://{self.goe_host}/api/status") as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('car', 0) == 2
                    return False
        except Exception as e:
            logger.error(f"Error getting GO-E status: {e}")
            return False

    async def get_tibber_prices(self) -> List[Dict]:
        """Get Tibber price information"""
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
                    self.tibber_url,
                    json={'query': query},
                    headers={"Authorization": f"Bearer {self.tibber_token}"}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        price_info = data['data']['viewer']['homes'][0]['currentSubscription']['priceInfo']

                        prices = []
                        if price_info.get('today'):
                            prices.extend(price_info['today'])
                        if price_info.get('tomorrow'):
                            prices.extend(price_info['tomorrow'])
                            logger.info("Tomorrow's prices are available")
                        else:
                            logger.info("Tomorrow's prices are not yet available")

                        return prices
                    else:
                        logger.error(f"Tibber API error: {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Error fetching Tibber prices: {e}")
            return []

    async def get_battery_status(self) -> BatteryStatus:
        """Get current battery status using sma_modbus.py approach"""
        try:
            # Read battery SoC (unsigned 32-bit)
            soc_registers = await self.read_sma_register(self.registers['battery_soc'])
            soc = self.decode_u32(soc_registers) if soc_registers else 0

            # Read grid power (signed 32-bit)
            power_registers = await self.read_sma_register(30865)  # Grid power exchange
            power = self.decode_s32(power_registers) if power_registers else 0

            # Read mode register (single register)
            mode_registers = await self.read_sma_register(40151, count=1)
            mode_value = mode_registers[0] if mode_registers else 803  # Default to NORMAL mode

            # Ensure mode_value maps to a valid BatteryMode
            if mode_value not in [mode.value for mode in BatteryMode]:
                mode_value = BatteryMode.NORMAL.value

            return BatteryStatus(
                soc=soc,
                power=power,
                mode=BatteryMode(mode_value),
                target_power=self.charge_power,
                is_charging=power > 0 if power is not None else False,
                temperature=0  # Temperature not available in sma_modbus.py
            )
        except Exception as e:
            logger.error(f"Error getting battery status: {e}")
            return None

    def find_best_charging_window(self, prices: List[Dict], hours_needed: int = 4) -> Dict:
        """Find best charging window based on relative price levels"""
        try:
            if not prices:
                logger.warning("No price data available")
                return None

            now = datetime.now().astimezone()
            future_prices = [
                p for p in prices
                if datetime.fromisoformat(p['startsAt']).astimezone() > now
            ]

            if len(future_prices) < hours_needed:
                logger.warning(f"Not enough future prices ({len(future_prices)} hours) for analysis")
                return None

            # Calculate price statistics for relative comparison
            price_values = [float(p['total']) for p in future_prices]
            avg_price = sum(price_values) / len(price_values)
            min_price = min(price_values)
            max_price = max(price_values)
            price_range = max_price - min_price

            # Log price overview
            logger.info("\nPrice Overview:")
            logger.info(f"Average: {avg_price*100:.1f} cents/kWh")
            logger.info(f"Minimum: {min_price*100:.1f} cents/kWh")
            logger.info(f"Maximum: {max_price*100:.1f} cents/kWh")
            logger.info(f"Range: {price_range*100:.1f} cents/kWh")

            # Log all future prices with relative comparison
            logger.info("\nFuture Price Analysis:")
            for price in future_prices:
                time = datetime.fromisoformat(price['startsAt']).strftime('%H:%M')
                price_value = float(price['total'])
                relative_position = (price_value - min_price) / price_range if price_range > 0 else 0
                relative_str = "BEST" if relative_position < 0.2 else (
                    "GOOD" if relative_position < 0.4 else (
                    "MEDIUM" if relative_position < 0.6 else (
                    "HIGH" if relative_position < 0.8 else "PEAK")))

                logger.info(
                    f"{time} - {price_value*100:.1f} cents/kWh "
                    f"({relative_str}, {relative_position*100:.0f}% above min)"
                )

            # Find best consecutive window based on relative prices
            best_window = None
            best_score = float('inf')  # Lower is better

            for i in range(len(future_prices) - hours_needed + 1):
                window = future_prices[i:i + hours_needed]
                window_prices = [float(p['total']) for p in window]
                avg_window_price = sum(window_prices) / len(window_prices)

                # Score based on:
                # 1. How close to minimum price (weighted 60%)
                # 2. Price stability in window (weighted 40%)
                price_position = (avg_window_price - min_price) / price_range if price_range > 0 else 0
                price_stability = (max(window_prices) - min(window_prices)) / price_range if price_range > 0 else 0
                window_score = 0.6 * price_position + 0.4 * price_stability

                start_time = datetime.fromisoformat(window[0]['startsAt'])
                end_time = datetime.fromisoformat(window[-1]['startsAt']) + timedelta(hours=1)

                logger.debug(
                    f"Window {start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}: "
                    f"avg={avg_window_price*100:.1f} cents/kWh, "
                    f"score={window_score:.2f} "
                    f"(position={price_position:.2f}, stability={price_stability:.2f})"
                )

                if window_score < best_score:
                    best_score = window_score
                    best_window = {
                        'start_time': start_time,
                        'end_time': end_time,
                        'average_price': avg_window_price,
                        'prices': window,
                        'score': window_score,
                        'relative_position': price_position
                    }

            if best_window:
                logger.info("\nBest Charging Window Found:")
                logger.info(f"Time: {best_window['start_time'].strftime('%H:%M')} - "
                          f"{best_window['end_time'].strftime('%H:%M')}")
                logger.info(f"Average Price: {best_window['average_price']*100:.1f} cents/kWh")
                logger.info(f"Relative Position: {best_window['relative_position']*100:.0f}% above minimum")
                logger.info(f"Window Score: {best_window['score']:.2f}")

                return best_window

            return None

        except Exception as e:
            logger.error(f"Error in find_best_charging_window: {e}")
            logger.exception("Detailed error trace:")
            return None

    async def set_battery_mode(self, mode: BatteryMode, power: int = 0):
        """Set battery mode and power with correct register values"""
        try:
            # First set the mode register (40151)
            mode_result = await self.write_sma_register(
                self.registers['battery_mode'],
                [0, mode.value]  # Format: [high_byte=0, low_byte=mode]
            )

            if not mode_result:
                logger.error(f"Failed to set battery mode to {mode.name}")
                return False

            await asyncio.sleep(5)  # 5-second delay as in YAML

            # Then set the power register (40149)
            if mode == BatteryMode.GRID_CHARGE:
                # For charging: 65535 - desired_power
                power_value = [65535, 65535 - power]
            elif mode == BatteryMode.NORMAL:
                # Normal mode doesn't need power setting
                return True
            else:
                # For pause or other modes: 0
                power_value = [0, 0]

            power_result = await self.write_sma_register(
                self.registers['battery_power'],
                power_value
            )

            if not power_result:
                logger.error(f"Failed to set battery power to {power}W")
                return False

            logger.info(f"Successfully set battery to {mode.name} mode with power {power}W")
            return True

        except Exception as e:
            logger.error(f"Error setting battery mode: {e}")
            return False

    async def write_sma_register(self, address: int, value: list) -> bool:
        """Write register to SMA inverter"""
        try:
            if not self.sma_client or not self.sma_client.connected:
                await self.connect_sma()

            # Convert single value to register pair if needed
            if isinstance(value, (int, float)):
                value = [
                    (int(value) >> 16) & 0xFFFF,  # High word
                    int(value) & 0xFFFF           # Low word
                ]

            # Try both address variants
            for base_adjust in [0, -1]:
                address_adj = address + base_adjust

                # Write registers
                if len(value) == 2:
                    result1 = self.sma_client.write_register(
                        address=address_adj,
                        value=value[0],
                        slave=self.sma_unit_id
                    )
                    result2 = self.sma_client.write_register(
                        address=address_adj + 1,
                        value=value[1],
                        slave=self.sma_unit_id
                    )
                    success = not (result1.isError() or result2.isError())
                else:
                    result = self.sma_client.write_register(
                        address=address_adj,
                        value=value[0],
                        slave=self.sma_unit_id
                    )
                    success = not result.isError()

                if success:
                    logger.debug(f"Successfully wrote {value} to register {address}")
                    return True

            logger.error(f"Failed to write to register {address}")
            return False

        except Exception as e:
            logger.error(f"Error writing register {address}: {e}")
            return False

    async def optimize_charging(self):
        """Main optimization logic with detailed price-based decisions"""
        try:
            logger.info("\n" + "="*50 + "\nStarting optimization cycle\n" + "="*50)

            # Get current status
            battery = await self.get_battery_status()
            car_charging = await self.get_car_charging_status()
            prices = await self.get_tibber_prices()

            if not battery or not prices:
                logger.error("Failed to get battery status or prices")
                return

            # Log current system state
            logger.info("\nCurrent System Status:")
            logger.info(f"Battery SoC: {battery.soc}%")
            logger.info(f"Battery Power: {battery.power}W")
            logger.info(f"Battery Mode: {battery.mode.name}")
            logger.info(f"Car Charging: {car_charging}")

            # Get current price and level
            now = datetime.now().astimezone()
            current_price_data = next(
                (p for p in prices
                 if datetime.fromisoformat(p['startsAt']).astimezone() <= now
                 <= datetime.fromisoformat(p['startsAt']).astimezone() + timedelta(hours=1)),
                None
            )

            if current_price_data:
                price_str = (f"{float(current_price_data['total'])*100:.1f} cents/kWh "
                           f"({current_price_data['level']})")
            else:
                price_str = "N/A"
            logger.info(f"Current price: {price_str}")

            # If car is charging, pause battery
            if car_charging:
                logger.info("\nCar charging detected - Pausing battery")
                await self.set_battery_mode(BatteryMode.PAUSE)
                return

            # Find best charging window
            best_window = self.find_best_charging_window(prices)
            if not best_window:
                logger.warning("No suitable charging window found")
                return

            # Check if in optimal charging window
            in_best_window = (
                best_window['start_time'] <= now <= best_window['end_time'] and
                best_window['score'] < 0.4  # Good relative price (among best 40% of opportunities)
            )

            # Decision making based on relative prices and battery status
            if battery.soc >= self.max_soc:
                logger.info("Battery sufficiently charged - switching to normal mode")
                await self.set_battery_mode(BatteryMode.NORMAL)

            elif battery.soc <= self.min_soc:
                logger.info("Emergency charging needed - battery below minimum")
                await self.set_battery_mode(BatteryMode.GRID_CHARGE, 1500)

            elif in_best_window:
                # Calculate optimal charging power based on price position and SoC
                base_power = min(5000, max(1500, int(5000 * (1 - battery.soc/100))))
                # Adjust power based on how good the price is
                power_factor = 1 - best_window['relative_position']  # Higher power for better prices
                power = int(base_power * (0.7 + 0.3 * power_factor))  # 70-100% of base power

                logger.info(
                    f"Charging at {power}W during optimal window "
                    f"(price position: {best_window['relative_position']*100:.0f}% above min)"
                )
                await self.set_battery_mode(BatteryMode.GRID_CHARGE, power)

            else:
                logger.info("Normal operation - waiting for better prices")
                await self.set_battery_mode(BatteryMode.NORMAL)

            logger.info("\n" + "="*50 + "\nOptimization cycle completed\n" + "="*50)

        except Exception as e:
            logger.error(f"Error in optimize_charging: {e}")
            logger.exception("Detailed error trace:")

    async def run(self):
        """Main control loop with timing information"""
        logger.info("\n" + "="*50)
        logger.info("Starting Smart Energy Controller")
        logger.info("Configuration:")
        logger.info(f"- Min SoC: {self.min_soc}%")
        logger.info(f"- Max SoC: {self.max_soc}%")
        logger.info(f"- Very cheap price threshold: {self.price_threshold_very_cheap}€/kWh")
        logger.info(f"- Cheap price threshold: {self.price_threshold_cheap}€/kWh")
        logger.info("=" * 50 + "\n")

        # Initial connection
        await self.connect_sma()

        while True:
            try:
                start_time = datetime.now()
                logger.info(f"\nStarting optimization cycle at {start_time.strftime('%H:%M:%S')}")

                await self.optimize_charging()

                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                logger.info(f"Cycle completed in {duration:.1f} seconds")
                logger.info(f"Next cycle in 5 minutes")

            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                logger.exception("Detailed error trace:")

            await asyncio.sleep(300)  # Run every 5 minutes

async def main():
    controller = SmartEnergyController()
    await controller.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")