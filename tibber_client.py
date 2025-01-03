import logging
import aiohttp
from typing import List, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

class TibberClient:
    def __init__(self, api_token: str):
        self.api_token = api_token
        self.api_url = "https://api.tibber.com/v1-beta/gql"

    async def get_prices(self) -> List[Dict]:
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
                    self.api_url,
                    json={'query': query},
                    headers={"Authorization": f"Bearer {self.api_token}"}
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

            # Calculate price statistics
            price_values = [float(p['total']) for p in future_prices]
            avg_price = sum(price_values) / len(price_values)
            min_price = min(price_values)
            max_price = max(price_values)
            price_range = max_price - min_price

            # Find best consecutive window
            best_window = None
            best_score = float('inf')

            for i in range(len(future_prices) - hours_needed + 1):
                window = future_prices[i:i + hours_needed]
                window_prices = [float(p['total']) for p in window]
                avg_window_price = sum(window_prices) / len(window_prices)

                price_position = (avg_window_price - min_price) / price_range if price_range > 0 else 0
                price_stability = (max(window_prices) - min(window_prices)) / price_range if price_range > 0 else 0
                window_score = 0.6 * price_position + 0.4 * price_stability

                if window_score < best_score:
                    best_score = window_score
                    best_window = {
                        'start_time': datetime.fromisoformat(window[0]['startsAt']),
                        'end_time': datetime.fromisoformat(window[-1]['startsAt']),
                        'average_price': avg_window_price,
                        'prices': window,
                        'score': window_score,
                        'relative_position': price_position
                    }

            return best_window

        except Exception as e:
            logger.error(f"Error in find_best_charging_window: {e}")
            logger.exception("Detailed error trace:")
            return None