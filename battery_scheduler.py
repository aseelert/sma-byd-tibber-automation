import asyncio
import logging
from datetime import datetime, timedelta
from battery_controller import BatteryController, BatteryMode

logger = logging.getLogger(__name__)

class BatteryScheduler:
    def __init__(self, battery_controller: BatteryController, tibber_client):
        self.controller = battery_controller
        self.tibber = tibber_client

    async def run(self):
        """Main scheduling loop"""
        while True:
            try:
                # Check if car is charging
                car_status = await self.controller.goe.get_status()
                if car_status.is_charging:
                    await self.controller.set_battery_mode(BatteryMode.PAUSE)
                    logger.info("Car charging detected - pausing battery")
                    await asyncio.sleep(300)  # Check again in 5 minutes
                    continue

                # Get battery status
                status = await self.controller.get_battery_status()
                if not status:
                    await asyncio.sleep(60)
                    continue

                # Get price data
                prices = await self.tibber.get_price_range(0, 24)

                # Determine optimal charging strategy
                if self.controller.should_charge(prices, status.soc):
                    # Calculate optimal charge power based on price
                    optimal_power = self.calculate_optimal_power(
                        prices[0]['total'],
                        status.soc
                    )

                    await self.controller.set_charge_power(optimal_power)
                    await self.controller.set_battery_mode(BatteryMode.GRID_CHARGE)
                    logger.info(f"Charging battery at {optimal_power}W")
                else:
                    await self.controller.set_battery_mode(BatteryMode.NORMAL)
                    logger.info("Normal battery operation")

            except Exception as e:
                logger.error(f"Scheduler error: {e}")

            await asyncio.sleep(300)  # Run every 5 minutes

    def calculate_optimal_power(self, price: float, soc: float) -> int:
        """Calculate optimal charging power based on price and SoC"""
        # Base power on price relative to daily average
        if price < 0.10:  # Very cheap
            base_power = 5000
        elif price < 0.15:  # Cheap
            base_power = 3500
        elif price < 0.20:  # Normal
            base_power = 2500
        else:  # Expensive
            base_power = 1500

        # Adjust based on SoC
        if soc < 30:
            return min(5000, base_power * 1.5)  # Charge faster when low
        elif soc > 80:
            return base_power * 0.7  # Charge slower when nearly full

        return base_power