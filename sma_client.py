import logging
from typing import Optional, List, Union
import asyncio
from pymodbus.client import ModbusTcpClient
from pymodbus.constants import Endian
from enum import Enum
from dataclasses import dataclass
from sma_registers import SMA_REGISTERS, RegisterType, RegisterFormat, BATTERY_STATUS

logger = logging.getLogger(__name__)

class BatteryMode(Enum):
    NORMAL = 803    # Normal/automatic operation (0x323)
    MANUAL = 802    # Manual power control mode (0x322)

    @staticmethod
    def from_registers(registers):
        """Convert register values to BatteryMode"""
        if len(registers) == 2:
            if registers == [255, 65533]:  # Alternative NORMAL mode values
                return BatteryMode.NORMAL

            mode_value = registers[1]
            if mode_value == 802:
                return BatteryMode.MANUAL
            elif mode_value == 803:
                return BatteryMode.NORMAL

        return BatteryMode.NORMAL  # Default to NORMAL mode

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
    operating_status: str    # Battery operating status (Charging/Discharging/Standby/etc)

class SMAClient:
    def __init__(self, host: str, port: int = 502, unit_id: int = 3):
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.client = None
        self.registers = SMA_REGISTERS

    async def connect(self) -> bool:
        """Connect to SMA inverter"""
        try:
            self.client = ModbusTcpClient(self.host, port=self.port)
            return self.client.connect()
        except Exception as e:
            logger.error(f"Error connecting to SMA: {e}")
            return False

    async def disconnect(self):
        """Disconnect from SMA inverter"""
        try:
            if self.client and self.client.connected:
                self.client.close()
                logger.debug("Disconnected from SMA inverter")
        except Exception as e:
            logger.error(f"Error disconnecting from SMA: {e}")

    async def read_registers(self, register_addr: int, count: int = 2) -> Optional[List[int]]:
        """Read registers with proper error handling"""
        try:
            if not self.client or not self.client.connected:
                if not await self.connect():
                    logger.error("Failed to connect to SMA client")
                    return None

            logger.debug(f"Reading register {register_addr} with count {count}")

            # Calculate base address based on register range
            if register_addr < 40000:
                base_address = register_addr
                result = self.client.read_input_registers(
                    address=base_address,
                    count=count,
                    slave=self.unit_id
                )
            else:
                base_address = register_addr
                result = self.client.read_holding_registers(
                    address=base_address,
                    count=count,
                    slave=self.unit_id
                )

            if result and not result.isError():
                logger.debug(f"Successfully read register {register_addr}: {result.registers}")
                return result.registers
            else:
                logger.error(f"Error reading register {register_addr}: {result}")
                return None

        except Exception as e:
            logger.error(f"Error reading register {register_addr}: {e}")
            return None

    def decode_u16(self, registers):
        """Decode unsigned 16-bit integer from register"""
        try:
            if not registers or len(registers) < 1:
                return 0
            return registers[0]
        except Exception as e:
            logger.error(f"Error decoding u16 value: {e}")
            return 0

    def decode_s16(self, registers):
        """Decode signed 16-bit integer from register"""
        try:
            if not registers or len(registers) < 1:
                return 0
            value = registers[0]
            # Convert to signed if necessary (two's complement)
            if value > 32767:
                value -= 65536
            return value
        except Exception as e:
            logger.error(f"Error decoding s16 value: {e}")
            return 0

    def decode_u32(self, registers):
        """Decode unsigned 32-bit integer from two registers"""
        try:
            if not registers or len(registers) != 2:
                return 0
            return self.client.convert_from_registers(
                registers,
                self.client.DATATYPE.UINT32,
                word_order=Endian.BIG
            )
        except Exception as e:
            logger.error(f"Error decoding u32 value: {e}")
            return 0

    def decode_s32(self, registers):
        """Decode signed 32-bit integer from two registers"""
        try:
            if not registers or len(registers) != 2:
                return 0
            return self.client.convert_from_registers(
                registers,
                self.client.DATATYPE.INT32,
                word_order=Endian.BIG
            )
        except Exception as e:
            logger.error(f"Error decoding s32 value: {e}")
            return 0

    def decode_u64(self, registers):
        """Decode unsigned 64-bit integer from four registers"""
        try:
            if not registers or len(registers) != 4:
                return 0
            return self.client.convert_from_registers(
                registers,
                self.client.DATATYPE.UINT64,
                word_order=Endian.BIG
            )
        except Exception as e:
            logger.error(f"Error decoding u64 value: {e}")
            return 0

    def decode_s64(self, registers):
        """Decode signed 64-bit integer from four registers"""
        try:
            if not registers or len(registers) != 4:
                return 0
            return self.client.convert_from_registers(
                registers,
                self.client.DATATYPE.INT64,
                word_order=Endian.BIG
            )
        except Exception as e:
            logger.error(f"Error decoding s64 value: {e}")
            return 0

    def decode_str(self, registers):
        """Decode string from registers"""
        try:
            if not registers:
                return ""
            # Convert registers to bytes and decode as ASCII
            bytes_data = b''.join(reg.to_bytes(2, 'big') for reg in registers)
            # Remove null bytes and decode
            return bytes_data.rstrip(b'\x00').decode('ascii')
        except Exception as e:
            logger.error(f"Error decoding string value: {e}")
            return ""

    async def read_register_value(self, register_name: str) -> Optional[Union[int, float, str]]:
        """Read a register using the register mapping"""
        try:
            register = self.registers[register_name]
            raw_values = await self.read_registers(register.address, register.count)

            if not raw_values:
                return None

            # Convert based on register type
            value = None
            if register.type == RegisterType.U16:
                value = self.decode_u16(raw_values)
            elif register.type == RegisterType.S16:
                value = self.decode_s16(raw_values)
            elif register.type == RegisterType.U32:
                value = self.decode_u32(raw_values)
            elif register.type == RegisterType.S32:
                value = self.decode_s32(raw_values)
            elif register.type == RegisterType.U64:
                value = self.decode_u64(raw_values)
            elif register.type == RegisterType.S64:
                value = self.decode_s64(raw_values)
            elif register.type == RegisterType.STR:
                value = self.decode_str(raw_values)
            else:
                logger.error(f"Unknown register type: {register.type}")
                return None

            # Apply scaling if needed
            if register.scale and value is not None:
                value *= register.scale

            return value

        except Exception as e:
            logger.error(f"Error reading register {register_name}: {e}")
            return None

    async def get_battery_status(self) -> Optional[BatteryStatus]:
        """Get current battery system status"""
        try:
            # Read raw register values using new register names
            soc_registers = await self.read_registers(self.registers['battery_soc'].address)
            grid_registers = await self.read_registers(self.registers['total_ac_power'].address)  # Changed from grid_power
            house_registers = await self.read_registers(self.registers['house_consumption'].address)
            battery_registers = await self.read_registers(self.registers['battery_power'].address)
            pv_registers = await self.read_registers(self.registers['total_dc_power'].address)    # Changed from dc_power_a
            mode_registers = await self.read_registers(self.registers['battery_control_mode'].address)
            battery_status_registers = await self.read_registers(self.registers['battery_charging_status'].address)

            # Debug logging for raw values
            if logger.getEffectiveLevel() <= logging.DEBUG:
                logger.debug(f"Raw SOC registers: {soc_registers}")
                logger.debug(f"Raw grid registers: {grid_registers}")
                logger.debug(f"Raw house registers: {house_registers}")
                logger.debug(f"Raw battery registers: {battery_registers}")
                logger.debug(f"Raw PV registers: {pv_registers}")
                logger.debug(f"Raw battery status registers: {battery_status_registers}")

            # Convert raw values
            soc = self.decode_u32(soc_registers) if soc_registers else 0
            grid_power = -self.decode_s32(grid_registers) if grid_registers else 0
            house_power = self.decode_s32(house_registers) if house_registers else 0
            battery_power = -self.decode_s32(battery_registers) if battery_registers else 0

            # Get battery status
            battery_status_value = self.decode_u32(battery_status_registers) if battery_status_registers else None
            battery_status = "Unknown"
            if battery_status_value in BATTERY_STATUS:
                battery_status = BATTERY_STATUS[battery_status_value]
                logger.debug(f"Battery Status: {battery_status}")

            # Get PV power (now using total DC power)
            pv_power = self.decode_s32(pv_registers) if pv_registers else 0

            # Get current operation mode
            current_mode = BatteryMode.from_registers(mode_registers) if mode_registers else BatteryMode.NORMAL

            # Debug logging for decoded values
            if logger.getEffectiveLevel() <= logging.DEBUG:
                logger.debug(f"Decoded SOC: {soc}%")
                logger.debug(f"Decoded grid power: {grid_power}W")
                logger.debug(f"Decoded house power: {house_power}W")
                logger.debug(f"Decoded battery power: {battery_power}W")
                logger.debug(f"Decoded PV power: {pv_power}W")
                logger.debug(f"Battery operating status: {battery_status}")

            return BatteryStatus(
                state_of_charge=soc,
                battery_power=battery_power,
                operation_mode=current_mode,
                target_power=battery_power,
                is_charging=battery_power > 0,
                temperature=0,
                grid_power_exchange=grid_power,
                house_power_consumption=house_power,
                solar_power_generation=pv_power,
                operating_status=battery_status
            )

        except Exception as e:
            logger.error(f"Error getting battery status: {e}")
            logger.exception("Detailed error trace:")
            return None

    async def set_battery_mode(self, mode: BatteryMode, power: int = 0) -> bool:
        """Set battery mode and power

        Args:
            mode: BatteryMode.NORMAL for automatic operation or
                 BatteryMode.MANUAL for manual power control
            power: Power setpoint in watts (positive=charging, negative=discharging, 0=pause)
                  Only used when mode is MANUAL
        """
        try:
            logger.info(f"Setting battery to {mode.name} mode" +
                       (f" with {power}W" if mode == BatteryMode.MANUAL else ""))

            # Get register definitions
            mode_register = self.registers['battery_control_mode']
            power_register = self.registers['battery_power_control']

            # Set mode values
            mode_values = [0, mode.value]
            mode_address = mode_register.address

            mode_result = self.client.write_registers(
                address=mode_address,
                values=mode_values,
                slave=self.unit_id
            )

            if mode_result.isError():
                logger.error(f"Failed to set mode: {mode_result}")
                return False

            # Set power if in MANUAL mode
            if mode == BatteryMode.MANUAL:
                await asyncio.sleep(1)  # Brief delay between writes

                # Convert power value to register values
                if power > 0:  # Charging
                    power_values = [65535, 65535 - power]
                elif power < 0:  # Discharging
                    power_values = [0, abs(power)]
                else:  # Pause
                    power_values = [0, 0]

                power_address = power_register.address
                power_result = self.client.write_registers(
                    address=power_address,
                    values=power_values,
                    slave=self.unit_id
                )

                if power_result.isError():
                    logger.error(f"Failed to set power: {power_result}")
                    return False

            logger.info(f"Successfully set battery to {mode.name} mode" +
                       (f" with {power}W" if mode == BatteryMode.MANUAL else ""))
            return True

        except Exception as e:
            logger.error(f"Error setting battery mode: {e}", exc_info=True)
            return False