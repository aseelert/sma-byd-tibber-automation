import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from enum import IntEnum
import os
import argparse
from sma_client import SMAClient, BatteryMode, BatteryStatus
from tibber_client import TibberClient
import aiohttp

# Create logger
logger = logging.getLogger(__name__)

class DebugLevel(IntEnum):
    NONE = 0    # Basic info only
    BASIC = 1   # Basic debug info
    DETAILED = 2  # Detailed debug info
    TRACE = 3   # Full trace with register values

# Setup logging
def setup_logging(debug_level: int):
    """Configure logging based on debug level"""
    base_format = '%(asctime)s - %(levelname)s - %(message)s'

    if debug_level >= DebugLevel.TRACE:
        logging.basicConfig(
            level=logging.DEBUG,
            format=base_format + ' - [%(filename)s:%(lineno)d]'
        )
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

class SmartEnergyController:
    def __init__(self, debug_level: int = DebugLevel.NONE):
        self.debug_level = debug_level

        # System configuration
        self.battery_capacity = 5000  # 5kWh battery
        self.min_charge_level = 20    # Minimum charge level for backup
        self.max_charge_level = 95    # Maximum charge level to preserve battery life
        self.optimal_charge_level = 80 # Optimal charge level for daily operation
        self.max_charging_power = 2500 # Default charging power (W)

        # Price thresholds in €/kWh
        self.price_threshold_very_low = 0.16
        self.price_threshold_low = 0.20
        self.price_threshold_normal = 0.25

        # Initialize clients
        self.sma = SMAClient(
            host=os.getenv('SMA_MODBUS_HOST', '192.168.178.57'),
            port=int(os.getenv('SMA_MODBUS_PORT', '502')),
            unit_id=int(os.getenv('SMA_MODBUS_UNIT_ID', '3'))
        )

        self.tibber = TibberClient(
            api_token=os.getenv('TIBBER_API_KEY')
        )

        # GO-E Configuration
        self.goe_host = os.getenv('GOE_HOST', '192.168.178.59')

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

    async def optimize_charging(self):
        """Main optimization logic with detailed price-based decisions"""
        try:
            logger.info("\n" + "="*50 + "\nStarting optimization cycle\n" + "="*50)

            # Get current system status using the SMA client
            battery_status = await self.sma.get_battery_status()
            car_charging_active = await self.get_car_charging_status()
            electricity_prices = await self.tibber.get_prices()

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
                await self.sma.set_battery_mode(BatteryMode.PAUSE)
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
                    await self.sma.set_battery_mode(BatteryMode.FAST_CHARGE, charging_power)
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
                await self.sma.set_battery_mode(BatteryMode.NORMAL)

            elif battery_status.state_of_charge <= self.min_charge_level:
                logger.info("Emergency charging needed - battery below minimum")
                await self.sma.set_battery_mode(BatteryMode.FAST_CHARGE, 1500)

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
                await self.sma.set_battery_mode(BatteryMode.FAST_CHARGE, power)

            else:
                logger.info("Normal operation - waiting for better prices")
                await self.sma.set_battery_mode(BatteryMode.NORMAL)

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
        await self.sma.connect()

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

    async def __aenter__(self):
        """Async context manager entry"""
        await self.sma.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.sma.disconnect()

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

        # Map command line arguments to battery modes
        mode_map = {
            'charge': (BatteryMode.MANUAL, args.power),      # Charge with specified power
            'discharge': (BatteryMode.MANUAL, -args.power),  # Discharge with specified power
            'pause': (BatteryMode.MANUAL, 0),               # Manual mode with 0 power
            'normal': (BatteryMode.NORMAL, 0)              # Normal/automatic operation
        }

        mode, power = mode_map[args.battery]

        async with controller as c:
            success = await c.sma.set_battery_mode(mode, power)
            if success:
                logger.info(f"Successfully set battery to {args.battery} mode" +
                           (f" with {abs(power)}W" if power != 0 else ""))
            else:
                logger.error(f"Failed to set battery mode to {args.battery}")
        return

    # Normal operation if no battery command
    await controller.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")