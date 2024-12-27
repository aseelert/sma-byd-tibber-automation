import logging
from pymodbus.client import ModbusTcpClient
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.exceptions import ModbusException
from dotenv import load_dotenv, find_dotenv
import os
from colorama import init, Fore, Back, Style

# Initialize colorama
init()

# Set up detailed logging
logging.basicConfig(
    level=logging.DEBUG,  # Changed to DEBUG for more information
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Enable pymodbus logging
pymodbus_logger = logging.getLogger('pymodbus')
pymodbus_logger.setLevel(logging.DEBUG)

# Load environment variables from .env file
load_dotenv(find_dotenv())

class SMAModbus:
    def __init__(self):
        # Get environment variables and clean up any comments
        host = os.getenv('SMA_MODBUS_HOST', '192.168.178.57')
        # Remove any comments from the host value
        self.host = host.split('#')[0].strip()

        if not self.host:
            logger.error("SMA_MODBUS_HOST not found in .env file")
            raise ValueError("SMA_MODBUS_HOST not configured")

        self.port = int(os.getenv('SMA_MODBUS_PORT', '502'))
        self.slave_id = int(os.getenv('SMA_MODBUS_UNIT_ID', '3'))
        self.show_raw = os.getenv('SMA_SHOW_RAW_ONLY', 'false').lower() == 'true'

        # Log configuration
        logger.info(f"Initializing SMA Modbus with: Host={self.host}, Port={self.port}, Slave ID={self.slave_id}")

        self.client = None

        # Updated register addresses for Sunny Tripower 6.0
        self.registers = {
            'grid_power': 30865,      # Grid power exchange
            'pv_power': 30775,        # Current power consumption
            'solar_power': 30773,     # Current solar generation power
            'battery_soc': 30845     # Battery State of Charge in %
        }

    def connect(self):
        """Establish Modbus TCP connection"""
        try:
            self.client = ModbusTcpClient(
                host=self.host,
                port=self.port,
                timeout=10
            )

            connected = self.client.connect()
            if connected:
                logger.info(f"Successfully connected to SMA inverter at {self.host}")
            else:
                logger.error(f"Failed to connect to SMA inverter at {self.host}")
            return connected

        except Exception as e:
            logger.error(f"Error connecting to SMA inverter: {e}")
            return False

    def disconnect(self):
        """Close Modbus TCP connection"""
        if self.client:
            self.client.close()

    def read_register(self, register_addr, count=2):
        """Read register with proper error handling"""
        try:
            logger.debug(f"Attempting to read register {register_addr} with count {count}")

            # Note: Some SMA inverters use 0-based addressing, others don't
            # Try both variants
            for base_adjust in [0, -1]:
                address = register_addr + base_adjust
                logger.debug(f"Trying address: {address}")

                result = self.client.read_holding_registers(
                    address=address,
                    count=count,
                    slave=self.slave_id
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

        except ModbusException as exc:
            logger.error(f"Modbus error reading register {register_addr}: {exc}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Error reading register {register_addr}: {e}", exc_info=True)
            return None

    def is_connected(self):
        """Check if client is connected"""
        return self.client is not None and self.client.connected

    def read_values(self):
        """Read all relevant values from inverter"""
        if not self.is_connected():
            logger.error("Not connected to SMA inverter")
            return None

        try:
            values = {}

            # Read Grid Power
            grid_registers = self.read_register(self.registers['grid_power'])
            if grid_registers:
                values['grid_power'] = self.decode_s32(grid_registers)

            # Read House Power Consumption
            pv_registers = self.read_register(self.registers['pv_power'])
            if pv_registers:
                values['house_power'] = self.decode_s32(pv_registers)

            # Read Solar Generation Power
            solar_registers = self.read_register(self.registers['solar_power'])
            if solar_registers:
                values['solar_power'] = self.decode_s32(solar_registers)

            # Read Battery SoC
            soc_registers = self.read_register(self.registers['battery_soc'])
            if soc_registers:
                values['battery_soc'] = self.decode_u32(soc_registers)  # Already in percentage, no conversion needed


            return values

        except Exception as e:
            logger.error(f"Error reading values: {e}", exc_info=True)
            return None

    def decode_s32(self, registers):
        """Decode signed 32-bit integer"""
        decoder = BinaryPayloadDecoder.fromRegisters(
            registers,
            byteorder=Endian.BIG,
            wordorder=Endian.BIG
        )
        return decoder.decode_32bit_int()

    def decode_u32(self, registers):
        """Decode unsigned 32-bit integer"""
        decoder = BinaryPayloadDecoder.fromRegisters(
            registers,
            byteorder=Endian.BIG,
            wordorder=Endian.BIG
        )
        return decoder.decode_32bit_uint()

async def main():
    sma = SMAModbus()

    print(f"\n{Back.BLUE}{Fore.WHITE}{'='*60}{Style.RESET_ALL}")
    print(f"{Back.BLUE}{Fore.WHITE}{'SMA SUNNY TRIPOWER 6.0 STATUS':^60}{Style.RESET_ALL}")
    print(f"{Back.BLUE}{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

    if sma.connect():
        try:
            values = sma.read_values()
            if values:
                print(f"\n{Fore.CYAN}╔{'═'*58}╗{Style.RESET_ALL}")
                print(f"{Fore.CYAN}║{Fore.YELLOW}{'INVERTER STATUS':^58}{Fore.CYAN}║{Style.RESET_ALL}")
                print(f"{Fore.CYAN}╠{'═'*58}╣{Style.RESET_ALL}")

                if sma.show_raw:
                    for key, value in values.items():
                        print(f"{Fore.CYAN}║{Style.RESET_ALL} {'Raw ' + key + ':':<20} {value:<35} {Fore.CYAN}║{Style.RESET_ALL}")

                # Grid Power
                if 'grid_power' in values:
                    power_color = Fore.RED if values['grid_power'] > 0 else Fore.GREEN
                    direction = "FROM GRID" if values['grid_power'] > 0 else "TO GRID"
                    power_str = f"{abs(values['grid_power'])} W ({direction})"
                    print(f"{Fore.CYAN}║{Style.RESET_ALL} {'Grid Power:':<20} {power_color}{power_str:<35}{Fore.CYAN}║{Style.RESET_ALL}")

                # House Power Consumption
                if 'house_power' in values:
                    house_str = f"{values['house_power']} W"
                    print(f"{Fore.CYAN}║{Style.RESET_ALL} {'House Power:':<20} {Fore.RED}{house_str:<35}{Fore.CYAN}║{Style.RESET_ALL}")

                # Solar Power Generation
                if 'solar_power' in values:
                    solar_str = f"{values['solar_power']} W"
                    print(f"{Fore.CYAN}║{Style.RESET_ALL} {'Solar Power:':<20} {Fore.YELLOW}{solar_str:<35}{Fore.CYAN}║{Style.RESET_ALL}")

                # Battery Status
                if 'battery_soc' in values:
                    soc_color = Fore.GREEN if values['battery_soc'] > 50 else Fore.YELLOW if values['battery_soc'] > 20 else Fore.RED
                    soc_str = f"{values['battery_soc']:.1f}%"
                    print(f"{Fore.CYAN}║{Style.RESET_ALL} {'Battery SoC:':<20} {soc_color}{soc_str:<35}{Fore.CYAN}║{Style.RESET_ALL}")

                if 'battery_power' in values:
                    bat_color = Fore.GREEN if values['battery_power'] < 0 else Fore.RED
                    direction = "CHARGING" if values['battery_power'] < 0 else "DISCHARGING"
                    bat_str = f"{abs(values['battery_power'])} W ({direction})"
                    print(f"{Fore.CYAN}║{Style.RESET_ALL} {'Battery Power:':<20} {bat_color}{bat_str:<35}{Fore.CYAN}║{Style.RESET_ALL}")

                # Battery Power Details
                if 'battery_charge' in values:
                    charge_str = f"{values['battery_charge']} W"
                    print(f"{Fore.CYAN}║{Style.RESET_ALL} {'Battery Charge:':<20} {Fore.GREEN}{charge_str:<35}{Fore.CYAN}║{Style.RESET_ALL}")

                if 'battery_discharge' in values:
                    discharge_str = f"{values['battery_discharge']} W"
                    print(f"{Fore.CYAN}║{Style.RESET_ALL} {'Battery Discharge:':<20} {Fore.RED}{discharge_str:<35}{Fore.CYAN}║{Style.RESET_ALL}")

                print(f"{Fore.CYAN}╚{'═'*58}╝{Style.RESET_ALL}\n")
        finally:
            sma.disconnect()

if __name__ == "__main__":
    import asyncio
    logger.info(f"Using configuration from: {find_dotenv()}")
    asyncio.run(main())
