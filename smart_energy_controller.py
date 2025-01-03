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
    FAST_CHARGE = 802      # Fast charging mode (same as pause but with positive power)
    FAST_DISCHARGE = 802   # Fast discharging mode (same as pause but with negative power)

    @staticmethod
    def is_auto_mode(registers):
        """Check if the registers indicate AUTO mode"""
        return registers == [255, 65533]

    @staticmethod
    def from_registers(registers, power_registers=None):
        """Convert register values to BatteryMode with power context"""
        if len(registers) == 2:
            # [255, 65533] is also NORMAL mode
            if registers == [255, 65533]:
                return BatteryMode.NORMAL

            mode_value = registers[1]
            if mode_value == 802:  # Need to determine specific mode based on power
                if power_registers and len(power_registers) == 2:
                    if power_registers[0] == 65535:  # Charging
                        return BatteryMode.FAST_CHARGE
                    elif power_registers[0] == 0 and power_registers[1] > 0:  # Discharging
                        return BatteryMode.FAST_DISCHARGE
                    else:  # No power set
                        return BatteryMode.PAUSE
                return BatteryMode.PAUSE
            elif mode_value == 803:
                return BatteryMode.NORMAL

        return BatteryMode.NORMAL

    @staticmethod
    def get_mode_name(mode, power=0):
        """Get the actual mode name based on mode and power"""
        if mode == BatteryMode.FAST_CHARGE and power > 0:
            return "FAST_CHARGE"
        elif mode == BatteryMode.FAST_DISCHARGE and power < 0:
            return "FAST_DISCHARGE"
        return mode.name

class BatteryChargingMode(Enum):
    FAST_CHARGING = 1767      # Schnelladung
    FULL_CHARGING = 1768      # Volladung
    BALANCE_CHARGING = 1769   # Ausgleichsladung
    MAINTENANCE = 1770        # Erhaltungsladung
    ENERGY_SAVING = 2184      # Energiesparen am Netz

    @staticmethod
    def from_value(value: int) -> 'BatteryChargingMode':
        """Convert register value to BatteryChargingMode"""
        try:
            return next(mode for mode in BatteryChargingMode if mode.value == value)
        except StopIteration:
            logger.warning(f"Unknown battery charging mode value: {value}")
            return None

    @property
    def description(self) -> str:
        """Get human-readable description of the mode"""
        descriptions = {
            BatteryChargingMode.FAST_CHARGING: "Fast Charging",
            BatteryChargingMode.FULL_CHARGING: "Full Charging",
            BatteryChargingMode.BALANCE_CHARGING: "Balance Charging",
            BatteryChargingMode.MAINTENANCE: "Maintenance Charging",
            BatteryChargingMode.ENERGY_SAVING: "Energy Saving"
        }
        return descriptions.get(self, "Unknown")

@dataclass
class BatteryStatus:
    state_of_charge: float    # Battery charge level (%)
    battery_power: int        # Current battery power (W)
    operation_mode: BatteryMode  # Current operation mode
    target_power: int        # Target battery power (W)
    is_charging: bool        # True if battery is charging
    temperature: float       # Battery temperature
    grid_power_exchange: int # Power exchanged with grid
    house_power_consumption: int  # Total house power consumption
    solar_power_generation: int   # Solar panel power generation
    charging_procedure: BatteryChargingMode = None  # Active charging procedure

class SmartEnergyController:
    def __init__(self, debug_level: int = DebugLevel.NONE):
        self.debug_level = debug_level
        load_dotenv()

        # System configuration
        self.battery_capacity = 5000  # 5kWh battery
        self.min_charge_level = 20    # Minimum charge level for backup
        self.max_charge_level = 95    # Maximum charge level to preserve battery life
        self.optimal_charge_level = 80 # Optimal charge level for daily operation
        self.max_charging_power = 2500 # Default charging power (W)

        # Price thresholds in €/kWh
        self.price_threshold_very_low = 0.10
        self.price_threshold_low = 0.15
        self.price_threshold_normal = 0.20

        # Register mapping for Modbus communication
        self.registers = {
            'grid_power_exchange': 30865,      # Power exchanged with the grid
            'house_power_consumption': 30773,  # Total power consumption of the house
            'solar_power_generation': 30775,   # Power generated by solar panels
            'battery_state_of_charge': 30845,  # Battery state of charge in percentage
            'battery_charging_status': 31397,  # Monitor for battery charging status
            'battery_discharging_status': 31401, # Monitor for battery discharging status
            'active_battery_charge_mode': 30853, # Current active battery charging procedure

            # Holding Registers (40xxx) for control
            'battery_operation_mode': 40151,   # Register for setting battery operation mode
            'battery_power_control': 40149     # Register for controlling battery power
        }

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

        # State tracking
        self.state_history: List[Dict] = []
        self.last_mode_change = datetime.now()

        # Create log directory
        self.log_dir = Path('logs')
        self.log_dir.mkdir(exist_ok=True)

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
                if not await self.connect_sma():
                    logger.error("Failed to connect to SMA client")
                    return None

            logger.debug(f"Attempting to read register {register_addr} with count {count}")

            # Calculate base address based on register range
            if register_addr < 40000:
                # Standard range - can use either type, but prefer input
                base_address = register_addr
                use_input = True
            else:
                # Holding registers (40xxx)
                base_address = register_addr
                use_input = False

            try:
                if use_input:
                    result = self.sma_client.read_input_registers(
                        address=base_address,
                        count=count,
                        slave=self.sma_unit_id
                    )
                else:
                    result = self.sma_client.read_holding_registers(
                        address=base_address,
                        count=count,
                        slave=self.sma_unit_id
                    )

                if result and not result.isError():
                    logger.debug(f"Successfully read register {register_addr} at address {base_address}: {result.registers}")
                    return result.registers
                else:
                    logger.error(f"Error reading register {register_addr}: {result}")

            except Exception as e:
                logger.error(f"Exception occurred while reading register {register_addr}: {e}")

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

    def decode_u32_enum(self, registers):
        """Decode unsigned 32-bit ENUM value from two registers"""
        try:
            # Create a temporary client if none exists
            client = self.sma_client or ModbusTcpClient(self.sma_host)

            # Use the client's built-in conversion method with updated Endian constant
            value = client.convert_from_registers(
                registers,
                client.DATATYPE.UINT32,
                word_order=Endian.BIG
            )

            # For U32 ENUM types, the value is in the second register
            # 40151 register values:
            # 802 = Active (PAUSE/FAST_CHARGE/FAST_DISCHARGE)
            # 803 = Inactive (NORMAL)
            logger.debug(f"U32 ENUM raw registers: {registers}, decoded value: {value}")
            return value

        except Exception as e:
            logger.error(f"Error decoding U32 ENUM value: {e}")
            return None

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
        """Get current battery system status"""
        try:
            # Read battery charge level
            charge_level_registers = await self.read_sma_register(self.registers['battery_state_of_charge'])
            current_charge_level = 0
            if charge_level_registers and len(charge_level_registers) == 2:
                current_charge_level = charge_level_registers[1]

            # Read grid exchange power
            grid_exchange_registers = await self.read_sma_register(self.registers['grid_power_exchange'])
            grid_exchange_power = 0
            if grid_exchange_registers and len(grid_exchange_registers) == 2:
                grid_exchange_power = self.decode_s32(grid_exchange_registers)

            # Read house consumption
            consumption_registers = await self.read_sma_register(self.registers['house_power_consumption'])
            house_consumption = 0
            if consumption_registers and len(consumption_registers) == 2:
                house_consumption = self.decode_s32(consumption_registers)

            # Read solar generation
            solar_registers = await self.read_sma_register(self.registers['solar_power_generation'])
            solar_generation = 0
            if solar_registers and len(solar_registers) == 2:
                solar_generation = self.decode_s32(solar_registers)

            # Calculate total house consumption
            total_house_consumption = grid_exchange_power + solar_generation

            # Read battery operation mode
            mode_registers = await self.read_sma_register(self.registers['battery_operation_mode'])
            current_mode = BatteryMode.NORMAL  # Default to NORMAL

            # Read battery power
            power_registers = await self.read_sma_register(self.registers['battery_power_control'])
            current_battery_power = 0
            if power_registers and len(power_registers) == 2:
                if power_registers[0] == 65535:  # Charging
                    current_battery_power = 65535 - power_registers[1]
                elif power_registers[0] == 0:    # Discharging
                    current_battery_power = -power_registers[1]

            return BatteryStatus(
                state_of_charge=current_charge_level,
                battery_power=current_battery_power,
                operation_mode=current_mode,
                target_power=current_battery_power,
                is_charging=current_battery_power > 0,
                temperature=0,
                grid_power_exchange=grid_exchange_power,
                house_power_consumption=total_house_consumption,
                solar_power_generation=solar_generation,
                charging_procedure=None
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
        """Set battery mode and power"""
        try:
            mode_name = BatteryMode.get_mode_name(mode, power)
            logger.info(f"Setting battery to {mode_name} mode" +
                       (f" with {abs(power)}W" if power != 0 else ""))

            # Set mode values - NORMAL mode can use either [0, 803] or [255, 65533]
            mode_values = [0, mode.value]
            logger.debug(f"Writing mode registers: values={mode_values}")

            mode_result = self.sma_client.write_registers(
                address=self.registers['battery_operation_mode'],
                values=mode_values,
                slave=self.sma_unit_id
            )

            if mode_result.isError():
                logger.error(f"Failed to set mode: {mode_result}")
                return False

            # Set power if needed
            if power != 0:
                await asyncio.sleep(5)

                power_values = [65535, 65535 - power] if power > 0 else [0, abs(power)]
                logger.debug(f"Writing power registers: values={power_values}")

                power_result = self.sma_client.write_registers(
                    address=self.registers['battery_power_control'],
                    values=power_values,
                    slave=self.sma_unit_id
                )

                if power_result.isError():
                    logger.error(f"Failed to set power: {power_result}")
                    return False

            logger.info(f"Successfully set battery to {mode_name} mode")
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

            # Get current system status
            battery_status = await self.get_battery_status()
            car_charging_active = await self.get_car_charging_status()
            electricity_prices = await self.get_tibber_prices()

            if not battery_status or not electricity_prices:
                logger.error("Failed to get system status or prices")
                return

            # Log current system state
            logger.info("\nCurrent System Status:")
            logger.info(f"Battery Charge Level: {battery_status.state_of_charge}%")
            logger.info(f"Grid Exchange Power: {battery_status.grid_power_exchange}W")
            logger.info(f"House Consumption: {battery_status.house_power_consumption}W")
            logger.info(f"Solar Generation: {battery_status.solar_power_generation}W")
            logger.info(f"Battery Mode: {battery_status.operation_mode.name}")
            logger.info(f"Car Charging: {car_charging_active}")

            # Check if car is charging - if so, set battery to pause
            if car_charging_active:
                logger.info("Car is charging - setting battery to PAUSE mode")
                await self.set_battery_mode(BatteryMode.PAUSE)
                return

            # Get current price and check if it's favorable
            now = datetime.now().astimezone()
            current_price_data = next(
                (p for p in electricity_prices
                 if datetime.fromisoformat(p['startsAt']).astimezone() <= now
                 <= datetime.fromisoformat(p['startsAt']).astimezone() + timedelta(hours=1)),
                None
            )

            if current_price_data:
                current_price = float(current_price_data['total'])
                price_values = [float(p['total']) for p in electricity_prices]
                min_price = min(price_values)
                max_price = max(price_values)
                price_range = max_price - min_price

                current_price_position = (current_price - min_price) / price_range if price_range > 0 else 0
                is_current_price_favorable = current_price_position <= 0.2

                logger.info(f"Current price position: {current_price_position*100:.1f}% above minimum")

                should_charge_now = (
                    is_current_price_favorable and
                    battery_status.state_of_charge < self.optimal_charge_level and
                    not car_charging_active
                )

                if should_charge_now:
                    # Calculate base charging power based on SoC
                    base_power = min(5000, max(1500, int(5000 * (1 - battery_status.state_of_charge/100))))

                    # Reduce power as we approach max SoC
                    soc_factor = 1.0
                    if battery_status.state_of_charge >= 85:
                        # Gradually reduce power from 100% to 20% between 85% and 95% SoC
                        soc_factor = 1.0 - (0.8 * (battery_status.state_of_charge - 85) / 10)
                        logger.info(f"Reducing charging power due to high SoC ({battery_status.state_of_charge}%), "
                                  f"factor: {soc_factor:.2f}")

                    # Adjust power based on price position
                    price_factor = 1 - current_price_position

                    # Calculate final charging power
                    charging_power = int(base_power * soc_factor * (0.7 + 0.3 * price_factor))

                    # Ensure minimum power threshold of 1000W
                    charging_power = max(1000, charging_power)

                    logger.info(
                        f"Starting to charge at {charging_power}W "
                        f"(base: {base_power}W, SoC factor: {soc_factor:.2f}, "
                        f"price factor: {price_factor:.2f})"
                    )
                    await self.set_battery_mode(BatteryMode.FAST_CHARGE, charging_power)
                    return

            # Find best charging window
            best_window = self.find_best_charging_window(electricity_prices)
            if not best_window:
                logger.warning("No suitable charging window found")
                return

            # Check if in optimal charging window
            in_best_window = (
                best_window['start_time'] <= now <= best_window['end_time'] and
                best_window['score'] < 0.4  # Good relative price (among best 40% of opportunities)
            )

            # Decision making based on relative prices and battery status
            if battery_status.state_of_charge >= self.max_charge_level:
                logger.info("Battery sufficiently charged - switching to normal mode")
                await self.set_battery_mode(BatteryMode.NORMAL)

            elif battery_status.state_of_charge <= self.min_charge_level:
                logger.info("Emergency charging needed - battery below minimum")
                await self.set_battery_mode(BatteryMode.FAST_CHARGE, 1500)

            elif in_best_window:
                # Calculate optimal charging power based on price position and SoC
                base_power = min(5000, max(1500, int(5000 * (1 - battery_status.state_of_charge/100))))
                # Adjust power based on how good the price is
                power_factor = 1 - best_window['relative_position']  # Higher power for better prices
                power = int(base_power * (0.7 + 0.3 * power_factor))  # 70-100% of base power

                logger.info(
                    f"Charging at {power}W during optimal window "
                    f"(price position: {best_window['relative_position']*100:.0f}% above min)"
                )
                await self.set_battery_mode(BatteryMode.FAST_CHARGE, power)

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
        logger.info(f"- Min SoC: {self.min_charge_level}%")
        logger.info(f"- Max SoC: {self.max_charge_level}%")
        logger.info(f"- Very cheap price threshold: {self.price_threshold_very_low}€/kWh")
        logger.info(f"- Cheap price threshold: {self.price_threshold_low}€/kWh")
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

    async def disconnect_sma(self):
        """Disconnect from SMA inverter"""
        try:
            if self.sma_client and self.sma_client.connected:
                self.sma_client.close()
                logger.debug("Disconnected from SMA inverter")
        except Exception as e:
            logger.error(f"Error disconnecting from SMA: {e}")

    async def __aenter__(self):
        """Async context manager entry"""
        await self.connect_sma()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.disconnect_sma()

def parse_args():
    parser = argparse.ArgumentParser(description='Smart Energy Controller')
    parser.add_argument('--debug', type=int, choices=[0, 1, 2, 3],
                       default=int(os.getenv('DEBUG_LEVEL', '0')),
                       help='Debug level (0=None, 1=Basic, 2=Detailed, 3=Trace)')
    parser.add_argument('--battery', type=str, choices=['charge', 'discharge', 'pause', 'normal'],
                       help='Force battery mode (charge/discharge/pause/normal)')
    parser.add_argument('--power', type=int, default=2000,
                       help='Power in watts for charging/discharging (default: 2000)')
    return parser.parse_args()

async def main():
    args = parse_args()
    setup_logging(args.debug)
    controller = SmartEnergyController(debug_level=args.debug)

    if args.battery:
        logger.info(f"Setting battery mode to: {args.battery}")

        # Map command line arguments directly to battery modes
        mode_map = {
            'charge': (BatteryMode.FAST_CHARGE, args.power),      # Changed from PAUSE to FAST_CHARGE
            'discharge': (BatteryMode.FAST_DISCHARGE, -args.power), # Changed from PAUSE to FAST_DISCHARGE
            'pause': (BatteryMode.PAUSE, 0),
            'normal': (BatteryMode.NORMAL, 0)
        }

        mode, power = mode_map[args.battery]

        # Connect to SMA
        await controller.connect_sma()

        # Set the requested mode
        success = await controller.set_battery_mode(mode, power)
        if success:
            logger.info(f"Successfully set battery to {args.battery} mode" +
                       (f" with {abs(power)}W" if power != 0 else ""))
        else:
            logger.error(f"Failed to set battery mode to {args.battery}")

        # Disconnect
        await controller.disconnect_sma()
        return

    # Normal operation if no battery command
    await controller.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")