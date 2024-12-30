import logging
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass

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
    last_full_charge: datetime  # Last time battery was fully charged

class BatteryController:
    def __init__(self, sma_client, goe_client):
        self.sma = sma_client
        self.goe = goe_client
        self.max_capacity = 5000  # 5kWh battery
        self.min_soc = 20        # Minimum SoC for backup
        self.max_soc = 95        # Maximum SoC to preserve battery life
        self.optimal_soc = 80    # Optimal SoC for daily operation
        self.charge_power = 2500 # Default charge power (W)

    async def get_battery_status(self) -> BatteryStatus:
        """Get current battery status from SMA inverter"""
        try:
            # Read relevant registers
            soc = await self.sma.read_register(40149)  # State of charge
            power = await self.sma.read_register(40151) # Current power
            mode = await self.sma.read_register(40151)  # Operating mode
            temp = await self.sma.read_register(40153)  # Temperature

            return BatteryStatus(
                soc=soc,
                power=power,
                mode=BatteryMode(mode),
                target_power=self.charge_power,
                is_charging=power > 0,
                temperature=temp,
                cycles=await self.sma.read_register(40157),
                last_full_charge=datetime.now()  # TODO: Get from register
            )
        except Exception as e:
            logger.error(f"Error reading battery status: {e}")
            return None

    async def set_battery_mode(self, mode: BatteryMode):
        """Set battery operating mode"""
        try:
            await self.sma.write_register(40151, mode.value)
            logger.info(f"Set battery mode to {mode.name}")
            return True
        except Exception as e:
            logger.error(f"Error setting battery mode: {e}")
            return False

    async def set_charge_power(self, power: int):
        """Set battery charge power in watts"""
        try:
            await self.sma.write_register(40149, power)
            self.charge_power = power
            logger.info(f"Set charge power to {power}W")
            return True
        except Exception as e:
            logger.error(f"Error setting charge power: {e}")
            return False

    def should_charge(self, price_data, soc: float) -> bool:
        """Determine if battery should charge based on price and SoC"""
        if soc >= self.max_soc:
            return False

        # If SoC is below minimum, charge regardless of price
        if soc <= self.min_soc:
            return True

        # Check if current price is in cheapest 20% of next 24h
        prices = [p['total'] for p in price_data]
        current_price = prices[0]
        price_threshold = sorted(prices)[:int(len(prices)*0.2)][-1]

        return current_price <= price_threshold