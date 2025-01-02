import asyncio
import logging
import json
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path
from pymodbus.client import ModbusTcpClient
from dotenv import load_dotenv
import os
from pymodbus.constants import Endian
import argparse

# Create logger
logger = logging.getLogger(__name__)

# Setup logging
def setup_logging(debug_level: int):
    """Configure logging based on debug level"""
    # Base format for all levels
    base_format = '%(asctime)s - %(levelname)s - %(message)s'

    if debug_level >= DebugLevel.TRACE:
        logging.basicConfig(
            level=logging.DEBUG,
            format=base_format + ' - [%(filename)s:%(lineno)d]'
        )
        # Enable pymodbus debug logging
        logging.getLogger('pymodbus').setLevel(logging.DEBUG)
    elif debug_level >= DebugLevel.DETAILED:
        logging.basicConfig(
            level=logging.DEBUG,
            format=base_format
        )
    elif debug_level >= DebugLevel.BASIC:
        logging.basicConfig(
            level=logging.INFO,
            format=base_format
        )
    else:
        logging.basicConfig(
            level=logging.WARNING,
            format=base_format
        )

class DebugLevel(IntEnum):
    NONE = 0    # Basic info only
    BASIC = 1   # Basic debug info
    DETAILED = 2  # Detailed debug info
    TRACE = 3   # Full trace with register values

class BatteryMode(Enum):
    NORMAL = 803           # Normal operation (0x323) - value [0, 803]
    PAUSE = 802            # Pause charging/discharging (0x322) - value [0, 802]
    GRID_CHARGE = 802      # Grid charge uses same mode as pause, but with power setting
    AUTO = 65533          # Automatic mode - value [255, 65533]

    @staticmethod
    def is_auto_mode(registers):
        """Check if the registers indicate AUTO mode"""
        return registers == [255, 65533]

    @staticmethod
    def from_registers(registers):
        """Convert register values to BatteryMode"""
        if BatteryMode.is_auto_mode(registers):
            return BatteryMode.AUTO
        elif len(registers) == 2:
            mode_value = registers[1]
            return next((mode for mode in BatteryMode if mode.value == mode_value), BatteryMode.NORMAL)
        return BatteryMode.NORMAL

@dataclass
class BatteryStatus:
    soc: float              # State of charge (%)
    power: int              # Current power (W)
    mode: BatteryMode       # Current operation mode
    target_power: int       # Target charging power (W)
    is_charging: bool       # True if currently charging
    temperature: float      # Battery temperature
    grid_power: int        # Grid power exchange
    pv_power: int          # House consumption
    solar_power: int       # Solar generation

class SmartEnergyController:
    def __init__(self, debug_level: int = DebugLevel.NONE):
        self.debug_level = debug_level
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

        # Updated register addresses to match working configuration
        self.registers = {
            'grid_power': 30865,      # Grid power exchange
            'pv_power': 30775,        # Current power consumption
            'solar_power': 30773,     # Current solar generation power
            'battery_soc': 30845,     # Battery State of Charge in %

            # Holding Registers (40xxx) for control
            'battery_mode': 40151,    # Battery operation mode register
            'battery_power': 40149    # Battery power control register
        }

    def log_register_debug(self, message: str, registers=None, level: int = DebugLevel.DETAILED):
        """Log register information based on debug level"""
        if self.debug_level >= level:
            if registers is not None:
                reg_hex = ' '.join([f'0x{r:04X}' for r in registers]) if registers else 'None'
                reg_dec = ' '.join([f'{r}' for r in registers]) if registers else 'None'
                reg_bin = ' '.join([f'{r:016b}' for r in registers]) if registers else 'None'
                logger.debug(f"{message}\n"
                           f"  HEX: {reg_hex}\n"
                           f"  DEC: {reg_dec}\n"
                           f"  BIN: {reg_bin}")
            else:
                logger.debug(message)

    async def connect_sma(self):
        """Connect to SMA inverter"""
        try:
            self.sma_client = ModbusTcpClient(self.sma_host, port=self.sma_port)
            return self.sma_client.connect()
        except Exception as e:
            logger.error(f"Error connecting to SMA: {e}")
            return False

    async def read_sma_register(self, register_addr, count=2):
        """Read register with proper error handling"""
        try:
            if not self.sma_client or not self.sma_client.connected:
                await self.connect_sma()

            logger.debug(f"Attempting to read register {register_addr} with count {count}")

            # Try both base-0 and base-1 addressing
            for base_adjust in [0, -1]:
                address = register_addr + base_adjust
                try:
                    result = self.sma_client.read_holding_registers(
                        address=address,
                        count=count,
                        slave=self.sma_unit_id
                    )

                    if result and not result.isError():
                        logger.debug(f"Successfully read register {register_addr} at address {address}: {result.registers}")
                        return result.registers

                except Exception as e:
                    logger.debug(f"Failed to read from address {address}: {e}")
                    continue

            logger.error(f"Failed to read register {register_addr}")
            return None

        except Exception as e:
            logger.error(f"Error reading register {register_addr}: {e}")
            return None

    def decode_s32(self, registers):
        """Decode signed 32-bit integer from two registers"""
        try:
            if not registers or len(registers) != 2:
                return 0

            # Create a temporary client if none exists
            client = self.sma_client or ModbusTcpClient(self.sma_host)

            # Use the client's built-in conversion method with updated Endian constant
            return client.convert_from_registers(
                registers,
                client.DATATYPE.INT32,
                word_order=Endian.BIG
            )

        except Exception as e:
            logger.error(f"Error decoding s32 value: {e}")
            return 0

    def decode_u32(self, registers):
        """Decode unsigned 32-bit integer from two registers"""
        try:
            if not registers or len(registers) != 2:
                return 0

            # Create a temporary client if none exists
            client = self.sma_client or ModbusTcpClient(self.sma_host)

            # Use the client's built-in conversion method with updated Endian constant
            return client.convert_from_registers(
                registers,
                client.DATATYPE.UINT32,
                word_order=Endian.BIG
            )

        except Exception as e:
            logger.error(f"Error decoding u32 value: {e}")
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
        """Get current battery status"""
        try:
            # Read battery SoC
            soc_registers = await self.read_sma_register(self.registers['battery_soc'])
            soc = 0
            if soc_registers and len(soc_registers) == 2:
                soc = soc_registers[1]
                logger.debug(f"Raw SoC registers: {soc_registers}, using value: {soc}")

            # Read grid power
            grid_registers = await self.read_sma_register(self.registers['grid_power'])
            grid_power = 0
            if grid_registers and len(grid_registers) == 2:
                grid_power = self.decode_s32(grid_registers)

            # Read house consumption
            pv_registers = await self.read_sma_register(self.registers['pv_power'])
            pv_power = 0
            if pv_registers and len(pv_registers) == 2:
                pv_power = self.decode_s32(pv_registers)

            # Read solar generation
            solar_registers = await self.read_sma_register(self.registers['solar_power'])
            solar_power = 0
            if solar_registers and len(solar_registers) == 2:
                solar_power = self.decode_s32(solar_registers)

            # Read mode register
            mode_registers = await self.read_sma_register(self.registers['battery_mode'], count=2)
            mode = BatteryMode.NORMAL
            if mode_registers and len(mode_registers) == 2:
                if mode_registers == [255, 65533]:  # Check for automatic mode
                    mode = BatteryMode.AUTO
                    logger.debug("Battery in automatic mode")
                else:
                    mode_value = mode_registers[1]  # Use second register value
                    mode = BatteryMode(mode_value) if mode_value in [m.value for m in BatteryMode] else BatteryMode.NORMAL
                logger.debug(f"Raw mode registers: {mode_registers}, using mode: {mode.name}")

            return BatteryStatus(
                soc=soc,
                power=grid_power,
                mode=mode,
                target_power=0,
                is_charging=grid_power > 0,
                temperature=0,
                grid_power=grid_power,
                pv_power=pv_power,
                solar_power=solar_power
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

    async def set_battery_mode(self, mode: BatteryMode, power: int = 0) -> bool:
        """Set battery operation mode"""
        try:
            # First check current mode
            current_mode = await self.read_sma_register(self.registers['battery_mode'], count=2)
            logger.debug(f"Current mode registers: {current_mode}")

            # If currently in AUTO mode and trying to set a different mode
            if current_mode == [255, 65533] and mode != BatteryMode.AUTO:
                logger.warning("Battery is in AUTO mode. Must disable AUTO mode first before setting other modes.")
                return False

            logger.info(f"Setting battery mode to {mode.name}" + (f" with power {power}W" if power else ""))

            # Rest of your existing code...
            if mode == BatteryMode.AUTO:
                mode_high = 255
                mode_low = 65533
            else:
                mode_high = 0
                mode_low = mode.value

            logger.debug(f"Writing to register {self.registers['battery_mode']}: high=[{mode_high}], low=[{mode_low}]")
            logger.debug(f"Using slave ID: {self.sma_unit_id}")

            # Verify connection before writing
            if not self.sma_client or not self.sma_client.connected:
                logger.debug("Client not connected, attempting to reconnect...")
                await self.connect_sma()
                if not self.sma_client.connected:
                    logger.error("Failed to reconnect to SMA inverter")
                    return False

            # Write mode to register with correct format
            mode_result1 = self.sma_client.write_register(
                address=self.registers['battery_mode'],
                value=mode_high,
                slave=self.sma_unit_id
            )

            logger.debug(f"First write result: {mode_result1}")
            if mode_result1.isError():
                logger.error(f"First write failed with error: {mode_result1}")

            # Add small delay between writes
            await asyncio.sleep(0.1)

            mode_result2 = self.sma_client.write_register(
                address=self.registers['battery_mode'] + 1,
                value=mode_low,
                slave=self.sma_unit_id
            )

            logger.debug(f"Second write result: {mode_result2}")
            if mode_result2.isError():
                logger.error(f"Second write failed with error: {mode_result2}")

            if mode_result1.isError() or mode_result2.isError():
                logger.error(f"Failed to set mode to {mode.name}")
                # Try to read current mode for debugging
                current_mode = await self.read_sma_register(self.registers['battery_mode'], count=2)
                logger.debug(f"Current mode registers: {current_mode}")
                return False

            # Only set power if not in AUTO mode
            if power != 0 and mode != BatteryMode.AUTO:
                if power > 0:  # Charging
                    power_high = 65535
                    power_low = 65535 - power
                else:  # Discharging
                    power_high = 0
                    power_low = abs(power)

                logger.debug(f"Setting power registers: High={power_high}, Low={power_low}")
                logger.debug(f"Writing to register {self.registers['battery_power']}")

                power_result1 = self.sma_client.write_register(
                    address=self.registers['battery_power'],
                    value=power_high,
                    slave=self.sma_unit_id
                )

                logger.debug(f"Power write result 1: {power_result1}")

                await asyncio.sleep(0.1)

                power_result2 = self.sma_client.write_register(
                    address=self.registers['battery_power'] + 1,
                    value=power_low,
                    slave=self.sma_unit_id
                )

                logger.debug(f"Power write result 2: {power_result2}")

                if power_result1.isError() or power_result2.isError():
                    logger.error(f"Failed to set power to {power}W")
                    return False

            logger.info(f"Successfully set battery mode to {mode.name}")
            return True

        except Exception as e:
            logger.error(f"Error setting battery mode: {e}", exc_info=True)
            return False

    async def write_sma_register(self, address: int, value: list) -> bool:
        """Write register with enhanced debug logging"""
        try:
            self.log_register_debug(
                f"Writing to register {address}:",
                value,
                DebugLevel.BASIC
            )

            if not self.sma_client or not self.sma_client.connected:
                await self.connect_sma()

            # SMA uses base-1 addressing
            address = address - 1

            # Write registers
            if len(value) == 2:
                result1 = self.sma_client.write_register(
                    address=address,
                    value=value[0],
                    slave=self.sma_unit_id
                )
                result2 = self.sma_client.write_register(
                    address=address + 1,
                    value=value[1],
                    slave=self.sma_unit_id
                )
                success = not (result1.isError() or result2.isError())

                self.log_register_debug(
                    f"Write results for register {address}:",
                    [
                        f"First write: {'Success' if not result1.isError() else 'Error'}",
                        f"Second write: {'Success' if not result2.isError() else 'Error'}"
                    ],
                    DebugLevel.TRACE
                )
            else:
                result = self.sma_client.write_register(
                    address=address,
                    value=value[0],
                    slave=self.sma_unit_id
                )
                success = not result.isError()
                self.log_register_debug(
                    f"Write result for register {address}:",
                    [f"Write: {'Success' if success else 'Error'}"],
                    DebugLevel.TRACE
                )

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
            logger.info(f"Grid Power Exchange: {battery.grid_power}")
            logger.info(f"House Consumption: {battery.pv_power}")
            logger.info(f"Solar Generation: {battery.solar_power}")
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

def parse_args():
    parser = argparse.ArgumentParser(description='Smart Energy Controller')
    parser.add_argument('--debug', type=int, choices=[0, 1, 2, 3],
                       default=int(os.getenv('DEBUG_LEVEL', '0')),
                       help='Debug level (0=None, 1=Basic, 2=Detailed, 3=Trace)')
    return parser.parse_args()

async def main():
    args = parse_args()
    setup_logging(args.debug)
    controller = SmartEnergyController(debug_level=args.debug)
    await controller.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")