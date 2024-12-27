import os
import logging
from datetime import datetime, timedelta
import aiohttp
import asyncio
from dotenv import load_dotenv
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TibberHandler:
    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv('TIBBER_API_KEY')
        self.api_url = 'https://api.tibber.com/v1-beta/gql'
        self.prices = []

    async def get_current_price(self):
        """Get current electricity price"""
        query = """
        {
          viewer {
            homes {
              currentSubscription{
                priceInfo{
                  current{
                    total
                    energy
                    tax
                    startsAt
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
                    self.api_url,
                    json={'query': query},
                    headers={'Authorization': f'Bearer {self.api_key}'}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        price_info = data['data']['viewer']['homes'][0]['currentSubscription']['priceInfo']['current']
                        return {
                            'total': price_info['total'],
                            'energy': price_info['energy'],
                            'tax': price_info['tax'],
                            'starts_at': price_info['startsAt']
                        }
                    else:
                        logger.error(f"Error getting current price: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Error in get_current_price: {e}")
            return None

    async def get_price_forecast(self):
        """Get price forecast for next 24 hours"""
        query = """
        {
          viewer {
            homes {
              currentSubscription{
                priceInfo{
                  today {
                    total
                    energy
                    tax
                    startsAt
                  }
                  tomorrow {
                    total
                    energy
                    tax
                    startsAt
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
                    self.api_url,
                    json={'query': query},
                    headers={'Authorization': f'Bearer {self.api_key}'}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        price_info = data['data']['viewer']['homes'][0]['currentSubscription']['priceInfo']

                        # Combine today and tomorrow prices
                        prices = price_info['today'] + price_info['tomorrow']

                        # Filter to next 24 hours
                        now = datetime.now()
                        future_prices = [
                            price for price in prices
                            if datetime.fromisoformat(price['startsAt'].replace('Z', '+00:00')) > now
                        ][:24]

                        self.prices = future_prices
                        return future_prices
                    else:
                        logger.error(f"Error getting price forecast: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Error in get_price_forecast: {e}")
            return None

    def plot_prices(self, save_path=None):
        """Plot price forecast"""
        if not self.prices:
            logger.error("No price data available")
            return

        # Prepare data
        times = [datetime.fromisoformat(p['startsAt'].replace('Z', '+00:00')) for p in self.prices]
        totals = [p['total'] for p in self.prices]

        # Find cheapest hours
        sorted_prices = sorted(zip(times, totals), key=lambda x: x[1])
        cheapest_times = [t for t, _ in sorted_prices[:6]]  # 6 cheapest hours

        # Create plot
        plt.figure(figsize=(12, 6))
        plt.plot(times, totals, marker='o')

        # Highlight cheapest hours
        for t in cheapest_times:
            plt.axvspan(t, t + timedelta(hours=1), color='green', alpha=0.2)

        # Format plot
        plt.title('Electricity Price Forecast')
        plt.xlabel('Time')
        plt.ylabel('Price (EUR/kWh)')
        plt.grid(True)

        # Format x-axis
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        plt.gcf().autofmt_xdate()

        if save_path:
            plt.savefig(save_path)
        else:
            plt.show()

        plt.close()

async def main():
    # Test the handler
    tibber = TibberHandler()

    # Get current price
    current_price = await tibber.get_current_price()
    print("\nCurrent price:", current_price)

    # Get and plot forecast
    forecast = await tibber.get_price_forecast()
    if forecast:
        print("\nPrice forecast for next 24 hours:")
        for price in forecast:
            print(f"Time: {price['startsAt']}, Price: {price['total']}")

        # Create price plot
        tibber.plot_prices('price_forecast.png')

if __name__ == "__main__":
    asyncio.run(main())