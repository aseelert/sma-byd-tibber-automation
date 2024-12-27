import os
import logging
import aiohttp
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from tibber_price import TibberPrice
from colorama import init, Fore, Back, Style

# Initialize colorama
init()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GoECharger:
    def __init__(self):
        load_dotenv()
        self.host = os.getenv('GOE_HOST')
        self.controller_host = os.getenv('GOE_CONTROLLER_HOST')
        self.api_version = os.getenv('GOE_API_VERSION', '2')
        self.base_url = f"http://{self.host}/api"
        self.controller_url = f"http://{self.controller_host}/api"
        self.tibber = TibberPrice()  # Initialize TibberPrice

    async def get_current_price(self):
        """Get current Tibber price"""
        return await self.tibber.get_current_price()

    async def get_charging_status(self):
        """Get essential charging information"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/status") as response:
                    if response.status == 200:
                        data = await response.json()
                        power_kw = float(data.get('nrg', [0]*12)[11]) / 1000.0

                        # Get current price from Tibber (with fallback)
                        price = await self.get_current_price() or 0
                        hourly_cost = power_kw * price if price else None

                        return {
                            'car_connected': self._get_car_status(data.get('car', 1)),
                            'charging_active': bool(data.get('alw', 0)),
                            'power_kw': power_kw,
                            'session_energy_kwh': float(data.get('dws', 0)) / 360000.0,
                            'charging_current_a': int(data.get('amp', 0)),
                            'phases_in_use': self._get_active_phases(data.get('nrg', [])),
                            'hourly_cost': hourly_cost,
                            'price_per_kwh': price
                        }
                    else:
                        logger.error(f"Error getting status: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Error in get_charging_status: {e}")
            return None

    def _get_car_status(self, status):
        """Convert numeric car status to descriptive string"""
        statuses = {
            1: "No car connected",
            2: "Charging",
            3: "Waiting for car",
            4: "Charging finished"
        }
        return statuses.get(status, "Unknown")

    def _get_active_phases(self, nrg_data):
        """Get active charging phases"""
        if len(nrg_data) >= 7:
            active_phases = []
            currents = [nrg_data[4], nrg_data[5], nrg_data[6]]  # L1, L2, L3 currents
            for i, current in enumerate(currents, 1):
                if current > 0:
                    active_phases.append(f"L{i}")
            return active_phases if active_phases else ["None"]
        return ["Unknown"]

    async def get_controller_status(self):
        """Get controller status with current consumption readings"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.controller_url}/status") as response:
                    if response.status == 200:
                        data = await response.json()

                        # Get current price from Tibber (with fallback)
                        price = await self.get_current_price() or 0

                        # Get current consumption values
                        channel_powers = data.get('ccp', [])  # Current Channel Power
                        channel_names = data.get('ccn', [])   # Channel Names

                        total_power = float(channel_powers[0]) if channel_powers else 0
                        total_power_kw = total_power / 1000.0
                        hourly_cost = abs(total_power_kw) * price if price else None

                        status = {
                            'total_power_w': total_power,
                            'direction': 'GRID FEED-IN' if total_power < 0 else 'CONSUMPTION',
                            'hourly_cost': hourly_cost,
                            'price_per_kwh': price,
                            'sensors': {}
                        }

                        appliances = {
                            'dishwasher': {'index': 9, 'name': 'Geschirrspüler', 'threshold': 100},
                            'heatpump': {'index': 10, 'name': 'Wärmepumpe', 'threshold': 200},
                            'oven': {'index': 11, 'name': 'Backofen', 'threshold': 150}
                        }

                        for key, appliance in appliances.items():
                            idx = appliance['index']
                            if idx < len(channel_powers) and channel_powers[idx] is not None:
                                power_w = float(channel_powers[idx])
                                power_kw = abs(power_w) / 1000.0
                                hourly_cost = power_kw * price if price else None

                                status['sensors'][key] = {
                                    'name': channel_names[idx] if idx < len(channel_names) else appliance['name'],
                                    'consumption_w': power_w,
                                    'active': abs(power_w) > appliance['threshold'],
                                    'hourly_cost': hourly_cost
                                }

                        return status
                    else:
                        logger.error(f"Error getting controller status: {response.status}")
                        return None

        except Exception as e:
            logger.error(f"Error in get_controller_status: {e}")
            return None

async def main():
    charger = GoECharger()

    print(f"\n{Back.BLUE}{Fore.WHITE}{'='*60}{Style.RESET_ALL}")
    print(f"{Back.BLUE}{Fore.WHITE}{'GO-E CHARGER & CONTROLLER STATUS':^60}{Style.RESET_ALL}")
    print(f"{Back.BLUE}{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

    # Get charger status
    status = await charger.get_charging_status()
    if status:
        print(f"\n{Fore.CYAN}╔{'═'*58}╗{Style.RESET_ALL}")
        print(f"{Fore.CYAN}║{Fore.YELLOW}{'CHARGER STATUS':^58}{Fore.CYAN}║{Style.RESET_ALL}")
        print(f"{Fore.CYAN}╠{'═'*58}╣{Style.RESET_ALL}")
        print(f"{Fore.CYAN}║{Style.RESET_ALL} {'Car Status:':<20} {status['car_connected']:<35} {Fore.CYAN}║{Style.RESET_ALL}")
        print(f"{Fore.CYAN}║{Style.RESET_ALL} {'Charging Active:':<20} {str(status['charging_active']):<35} {Fore.CYAN}║{Style.RESET_ALL}")
        print(f"{Fore.CYAN}║{Style.RESET_ALL} {'Current Power:':<20} {f'{status['power_kw']:.2f} kW':<35} {Fore.CYAN}║{Style.RESET_ALL}")
        if status['hourly_cost'] is not None:
            print(f"{Fore.CYAN}║{Style.RESET_ALL} {'Estimated Cost:':<20} {f'{status['hourly_cost']:.2f} €/hour':<35} {Fore.CYAN}║{Style.RESET_ALL}")
            print(f"{Fore.CYAN}║{Style.RESET_ALL} {'Current Price:':<20} {f'{status['price_per_kwh']:.2f} €/kWh':<35} {Fore.CYAN}║{Style.RESET_ALL}")
        print(f"{Fore.CYAN}║{Style.RESET_ALL} {'Session Energy:':<20} {f'{status['session_energy_kwh']:.2f} kWh':<35} {Fore.CYAN}║{Style.RESET_ALL}")
        print(f"{Fore.CYAN}║{Style.RESET_ALL} {'Charging Current:':<20} {f'{status['charging_current_a']} A':<35} {Fore.CYAN}║{Style.RESET_ALL}")
        print(f"{Fore.CYAN}║{Style.RESET_ALL} {'Active Phases:':<20} {', '.join(status['phases_in_use']):<35} {Fore.CYAN}║{Style.RESET_ALL}")
        print(f"{Fore.CYAN}╚{'═'*58}╝{Style.RESET_ALL}")

    # Get controller status
    controller = await charger.get_controller_status()
    if controller:
        print(f"\n{Fore.GREEN}╔{'═'*58}╗{Style.RESET_ALL}")
        print(f"{Fore.GREEN}║{Fore.YELLOW}{'HOUSE POWER STATUS':^58}{Fore.GREEN}║{Style.RESET_ALL}")
        print(f"{Fore.GREEN}╠{'═'*58}╣{Style.RESET_ALL}")

        # Show total power with direction and cost
        direction_color = Fore.RED if controller['direction'] == 'CONSUMPTION' else Fore.GREEN
        power_str = f"{abs(controller['total_power_w']):.3f} W"
        direction_str = f"({controller['direction']})"
        print(f"{Fore.GREEN}║{Style.RESET_ALL} {power_str:<25} {direction_color}{direction_str:<30}{Fore.GREEN}║{Style.RESET_ALL}")

        if controller['hourly_cost'] is not None:
            print(f"{Fore.GREEN}║{Style.RESET_ALL} {'Est. Cost:':<20} {f'{controller['hourly_cost']:.2f} €/hour':<35} {Fore.GREEN}║{Style.RESET_ALL}")
            print(f"{Fore.GREEN}║{Style.RESET_ALL} {'Current Price:':<20} {f'{controller['price_per_kwh']:.2f} €/kWh':<35} {Fore.GREEN}║{Style.RESET_ALL}")
        print(f"{Fore.GREEN}╚{'═'*58}╝{Style.RESET_ALL}")

        # Print current consumption for each appliance
        print(f"\n{Fore.MAGENTA}╔{'═'*58}╗{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}║{Fore.YELLOW}{'APPLIANCE CONSUMPTION':^58}{Fore.MAGENTA}║{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}╠{'═'*58}╣{Style.RESET_ALL}")

        for device_name, sensor_data in controller['sensors'].items():
            if sensor_data:
                status_color = Fore.GREEN if sensor_data['active'] else Fore.RED
                status = "RUNNING" if sensor_data['active'] else "OFF"
                power_str = f"{sensor_data['consumption_w']:.3f} W"
                name_str = f"{sensor_data['name']:<15}"
                status_str = f"({status})"

                print(f"{Fore.MAGENTA}║{Style.RESET_ALL} {name_str} {power_str:<15} {status_color}{status_str:<15}{Fore.MAGENTA}║{Style.RESET_ALL}")

                if sensor_data['hourly_cost'] is not None:
                    cost_str = f"Est. Cost: {sensor_data['hourly_cost']:.2f} €/hour"
                    print(f"{Fore.MAGENTA}║{Style.RESET_ALL} {cost_str:<56} {Fore.MAGENTA}║{Style.RESET_ALL}")

        print(f"{Fore.MAGENTA}╚{'═'*58}╝{Style.RESET_ALL}\n")

if __name__ == "__main__":
    asyncio.run(main())