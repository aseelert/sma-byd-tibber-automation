import os
import logging
import aiohttp
from dotenv import load_dotenv
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TibberPrice:
    def __init__(self):
        load_dotenv()
        self.token = os.getenv('TIBBER_API_KEY')
        if not self.token:
            logger.warning("No Tibber token found in .env file")
        self.url = "https://api.tibber.com/v1-beta/gql"

    async def get_current_price(self):
        """Get current Tibber price in kr/kWh"""
        if not self.token:
            logger.warning("Cannot get price: No Tibber token available")
            return None

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
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(self.url, json={'query': query}, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'errors' in data:
                            logger.error(f"GraphQL errors: {data['errors']}")
                            return None
                        try:
                            price_info = data['data']['viewer']['homes'][0]['currentSubscription']['priceInfo']['current']
                            return price_info['total']  # Returns total price including tax
                        except (KeyError, IndexError) as e:
                            logger.error(f"Unexpected response structure: {e}")
                            return None
                    else:
                        response_text = await response.text()
                        logger.error(f"Error getting Tibber price: Status {response.status}, Response: {response_text}")
                        return None
        except Exception as e:
            logger.error(f"Error in get_current_price: {str(e)}")
            return None

    async def get_price_range(self, hours_past=12, hours_future=24):
        """Get price information for a range of hours"""
        if not self.token:
            logger.error("Cannot get prices: No Tibber token available")
            return []

        query = """
        {
          viewer {
            homes {
              currentSubscription{
                priceInfo{
                  current {
                    total
                    energy
                    tax
                    startsAt
                  }
                  today {
                    total
                    energy
                    tax
                    startsAt
                    level
                  }
                  tomorrow {
                    total
                    energy
                    tax
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
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }

            logger.debug(f"Fetching Tibber prices with token: {self.token[:10]}...")

            async with aiohttp.ClientSession() as session:
                async with session.post(self.url, json={'query': query}, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()

                        try:
                            price_info = data['data']['viewer']['homes'][0]['currentSubscription']['priceInfo']
                            today = price_info.get('today', []) or []
                            tomorrow = price_info.get('tomorrow', []) or []

                            # Log availability of tomorrow's prices
                            if tomorrow:
                                logger.info("Tomorrow's prices are available")
                            else:
                                logger.info("Tomorrow's prices are not yet available")

                            # Combine and filter based on time range
                            all_prices = []
                            if isinstance(today, list):
                                all_prices.extend(today)
                            if isinstance(tomorrow, list):
                                all_prices.extend(tomorrow)

                            now = datetime.now().astimezone()
                            start_time = now - timedelta(hours=hours_past)
                            end_time = now + timedelta(hours=hours_future)

                            filtered_prices = []
                            for price in all_prices:
                                try:
                                    price_time = datetime.fromisoformat(price['startsAt']).astimezone()
                                    if start_time <= price_time <= end_time:
                                        filtered_prices.append(price)
                                except (ValueError, TypeError) as e:
                                    logger.warning(f"Invalid datetime in price data: {price.get('startsAt')} - {e}")
                                    continue

                            # Sort prices by time
                            filtered_prices.sort(key=lambda x: datetime.fromisoformat(x['startsAt']))

                            # Log the time range of available prices
                            if filtered_prices:
                                first_time = datetime.fromisoformat(filtered_prices[0]['startsAt']).astimezone()
                                last_time = datetime.fromisoformat(filtered_prices[-1]['startsAt']).astimezone()
                                logger.info(f"Price data available from {first_time.strftime('%Y-%m-%d %H:%M')} "
                                          f"to {last_time.strftime('%Y-%m-%d %H:%M')}")

                            return filtered_prices

                        except (KeyError, IndexError) as e:
                            logger.error(f"Unexpected response structure: {e}")
                            return []
                    else:
                        logger.error(f"Error getting Tibber prices: Status {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Error in get_price_range: {str(e)}")
            return []

    async def test_connection(self):
        """Test the Tibber API connection and print detailed information"""
        query = """
        {
          viewer {
            homes {
              id
              address {
                address1
                postalCode
                city
              }
              currentSubscription{
                status
              }
            }
          }
        }
        """

        try:
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(self.url, json={'query': query}, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        print("\nTibber Connection Test:")
                        print("=" * 50)
                        if 'errors' in data:
                            print(f"API Error: {data['errors']}")
                        else:
                            homes = data['data']['viewer']['homes']
                            for home in homes:
                                print(f"Home ID: {home['id']}")
                                print(f"Address: {home['address']['address1']}")
                                print(f"Location: {home['address']['postalCode']} {home['address']['city']}")
                                print(f"Subscription Status: {home['currentSubscription']['status']}")
                    else:
                        print(f"Connection failed with status {response.status}")

        except Exception as e:
            print(f"Connection test failed: {e}")

async def main():
    """Test function"""
    tibber = TibberPrice()

    # Test connection first
    await tibber.test_connection()

    # Then test price fetching
    price = await tibber.get_current_price()
    if price is not None:
        print(f"\nCurrent Tibber price: {price:.2f} €/kWh")
    else:
        print("\nFailed to get price")
        if not tibber.token:
            print("Please check your TIBBER_API_KEY in .env file")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())