import os
import json
import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from tibber_price import TibberPrice
from colorama import init, Fore, Style
from pyecharts import options as opts
from pyecharts.charts import Line, Bar, Grid, Page
from pyecharts.commons.utils import JsCode

# Initialize colorama
init()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EnergyOptimizer:
    def __init__(self):
        load_dotenv()
        self.tibber = TibberPrice()

        # Solar forecast parameters
        self.lat = os.getenv('SOLAR_LAT', '52.0')
        self.lon = os.getenv('SOLAR_LON', '13.0')
        self.dec = os.getenv('SOLAR_DECLINATION', '35')
        self.az = os.getenv('SOLAR_AZIMUTH', '0')
        self.kwp = os.getenv('SOLAR_KWP', '5.0')
        self.solar_api_key = os.getenv('SOLAR_API_KEY')

        # Cache settings
        self.cache_dir = Path('cache')
        self.cache_dir.mkdir(exist_ok=True)
        self.solar_cache_file = self.cache_dir / 'solar_forecast.json'
        self.solar_cache_duration = timedelta(hours=2)

    def save_solar_data(self, data, filename="solar_data.json"):
        """Save solar forecast data with timestamp and metadata"""
        try:
            # Create data directory if it doesn't exist
            data_dir = Path('data')
            data_dir.mkdir(exist_ok=True)

            # Prepare data structure
            storage_data = {
                'timestamp': datetime.now().isoformat(),
                'location': {
                    'latitude': self.lat,
                    'longitude': self.lon,
                    'declination': self.dec,
                    'azimuth': self.az,
                    'kwp': self.kwp
                },
                'forecast': data
            }

            # Save to file with date in filename
            date_str = datetime.now().strftime('%Y%m%d')
            filepath = data_dir / f"solar_forecast_{date_str}.json"

            # Load existing data if file exists
            if filepath.exists():
                with open(filepath, 'r') as f:
                    try:
                        existing_data = json.load(f)
                        if isinstance(existing_data, list):
                            existing_data.append(storage_data)
                        else:
                            existing_data = [existing_data, storage_data]
                    except json.JSONDecodeError:
                        existing_data = [storage_data]
            else:
                existing_data = [storage_data]

            # Write updated data
            with open(filepath, 'w') as f:
                json.dump(existing_data, f, indent=2)

            logger.info(f"Solar forecast data saved to {filepath}")
            return True

        except Exception as e:
            logger.error(f"Error saving solar data: {e}")
            return False

    def load_solar_data(self, date=None):
        """Load solar forecast data for a specific date"""
        try:
            data_dir = Path('data')
            if not date:
                date = datetime.now()

            date_str = date.strftime('%Y%m%d')
            filepath = data_dir / f"solar_forecast_{date_str}.json"

            if not filepath.exists():
                logger.warning(f"No solar data found for {date_str}")
                return None

            with open(filepath, 'r') as f:
                data = json.load(f)
                logger.info(f"Loaded solar data from {filepath}")
                return data

        except Exception as e:
            logger.error(f"Error loading solar data: {e}")
            return None

    async def get_solar_forecast(self):
        """Get solar forecast from forecast.solar API with caching"""
        now = datetime.now()

        # Check cache first
        if self.solar_cache_file.exists():
            with open(self.solar_cache_file) as f:
                cache = json.load(f)
                cache_time = datetime.fromisoformat(cache['timestamp'])
                if now - cache_time < self.solar_cache_duration:
                    logger.info("Using cached solar forecast")
                    return cache['data']

        # If cache is invalid or doesn't exist, fetch new data
        url = (f"https://api.forecast.solar/estimate/{self.lat}/{self.lon}/"
               f"{self.dec}/{self.az}/{self.kwp}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    response_text = await response.text()
                    logger.debug(f"Solar API response: {response_text}")

                    if response.status == 200:
                        try:
                            data = await response.json()
                            if not data or 'result' not in data:
                                logger.error(f"Invalid response format from solar API: {data}")
                                return None

                            # Save the forecast data
                            self.save_solar_data(data)

                            # Cache the results
                            cache_data = {
                                'timestamp': now.isoformat(),
                                'data': data
                            }
                            with open(self.solar_cache_file, 'w') as f:
                                json.dump(cache_data, f)

                            return data
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse solar API response: {e}")
                            return None
                    else:
                        logger.error(f"Solar API error: {response.status} - {response_text}")
                        return None
        except Exception as e:
            logger.error(f"Error fetching solar forecast: {e}")
            return None

    def create_price_chart(self, prices, best_window=None):
        """Create price visualization using pyecharts"""
        time_labels = []
        price_values = []
        price_colors = []
        markpoint_data = []  # For marking cheapest points
        now = datetime.now().astimezone()

        best_start = best_window['start_time'] if best_window else None
        best_end = best_window['end_time'] if best_window else None

        # Find absolute cheapest future price
        future_prices = [
            float(p['total']) * 100
            for p in prices
            if datetime.fromisoformat(p['startsAt']).astimezone() > now
        ]
        min_future_price = min(future_prices) if future_prices else None

        for price_data in prices:
            dt = datetime.fromisoformat(price_data['startsAt']).astimezone()
            time_labels.append(dt.strftime('%H:%M'))
            price = price_data['total'] * 100  # Convert to cents
            price_values.append(price)

            # Set color based on price level and best window
            is_best = best_start and best_start <= dt <= best_end
            is_future = dt > now
            level = price_data.get('level', 'NORMAL')

            # Use dimmed colors for historical data
            if not is_future:
                color = "#cccccc"  # Gray for historical data
            else:
                color = self.get_price_color(level, is_best)
            price_colors.append(color)

            # Mark cheapest future price points
            if is_future and min_future_price and price == min_future_price:
                markpoint_data.append({
                    "name": "Lowest Future",
                    "coord": [dt.strftime('%H:%M'), price],
                    "value": f"{price:.1f}¢",
                    "symbol_size": 35,
                    "itemStyle": {"color": "#2ecc71"}
                })

        # Create price chart
        price_chart = Bar(init_opts=opts.InitOpts(
            theme="white",
            width="1200px",
            height="600px"
        ))

        price_chart.add_xaxis(time_labels)
        price_chart.add_yaxis(
            "Price (€ cents/kWh)",
            price_values,
            itemstyle_opts=opts.ItemStyleOpts(
                color=JsCode(
                    """function(params) {
                        var colors = %s;
                        return colors[params.dataIndex];
                    }""" % price_colors
                )
            ),
            markpoint_opts=opts.MarkPointOpts(data=markpoint_data),
            label_opts=opts.LabelOpts(
                position="top",
                font_size=10,
                formatter="{c:.1f}¢"
            )
        )

        # Add best window annotation
        if best_window:
            subtitle = (
                f"Best future charging window: {best_start.strftime('%H:%M')} - {best_end.strftime('%H:%M')}\n"
                f"Average price: {best_window['average_price']*100:.1f} cents/kWh"
            )
        else:
            subtitle = "No optimal future charging window found"

        # Configure chart options
        price_chart.set_global_opts(
            title_opts=opts.TitleOpts(
                title="Energy Prices",
                subtitle=subtitle,
                subtitle_textstyle_opts=opts.TextStyleOpts(
                    color="#2ecc71",
                    font_size=14
                ),
                pos_left="center"
            ),
            xaxis_opts=opts.AxisOpts(
                type_="category",
                axislabel_opts=opts.LabelOpts(
                    rotate=45,
                    font_size=12
                ),
                splitline_opts=opts.SplitLineOpts(
                    is_show=True,
                    linestyle_opts=opts.LineStyleOpts(opacity=0.2)
                )
            ),
            yaxis_opts=opts.AxisOpts(
                type_="value",
                axislabel_opts=opts.LabelOpts(
                    formatter="{value} cents",
                    font_size=12
                ),
                splitline_opts=opts.SplitLineOpts(
                    is_show=True,
                    linestyle_opts=opts.LineStyleOpts(opacity=0.2)
                )
            ),
            tooltip_opts=opts.TooltipOpts(
                trigger="axis",
                axis_pointer_type="cross",
                background_color="rgba(255,255,255,0.9)",
                border_color="#ccc",
                border_width=1,
                textstyle_opts=opts.TextStyleOpts(color="#666"),
                formatter=JsCode(
                    """function(params) {
                        var time = params[0].name;
                        var price = params[0].value;
                        var color = params[0].color;
                        return '<div style="padding: 3px;">' +
                               '<strong>' + time + '</strong><br/>' +
                               '<span style="color:' + color + '">●</span> ' +
                               'Price: ' + price.toFixed(1) + ' cents/kWh' +
                               '</div>';
                    }"""
                )
            ),
            datazoom_opts=[
                opts.DataZoomOpts(range_start=0, range_end=100),
                opts.DataZoomOpts(type_="inside")
            ]
        )

        return price_chart

    def create_solar_chart(self, solar_forecast):
        """Create solar production visualization using pyecharts"""
        if not solar_forecast or 'result' not in solar_forecast:
            return None

        solar_data = solar_forecast.get('result', {}).get('watts', {})
        if not solar_data:
            logger.error("No solar production data found in forecast")
            return None

        times = []
        production = []

        for timestamp, watts in solar_data.items():
            try:
                dt = datetime.fromisoformat(timestamp)
                times.append(dt.strftime('%H:%M'))
                production.append(watts / 1000)  # Convert W to kW
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid data point in solar forecast: {timestamp} - {e}")
                continue

        if not times:
            logger.error("No valid solar production data points found")
            return None

        # Create solar chart
        solar_chart = Line(init_opts=opts.InitOpts(
            theme="white",
            width="1200px",
            height="400px"
        ))

        solar_chart.add_xaxis(times)
        solar_chart.add_yaxis(
            "Solar Production (kW)",
            production,
            is_smooth=True,
            symbol_size=8,
            linestyle_opts=opts.LineStyleOpts(width=3),
            itemstyle_opts=opts.ItemStyleOpts(color="#FFB01D"),
            label_opts=opts.LabelOpts(
                is_show=True,
                position="top",
                formatter="{c:.1f}kW",
                font_size=10,
                color="#666"
            )
        )

        solar_chart.set_global_opts(
            title_opts=opts.TitleOpts(
                title="Solar Production Forecast",
                pos_left="center"
            ),
            xaxis_opts=opts.AxisOpts(
                type_="category",
                axislabel_opts=opts.LabelOpts(
                    rotate=45,
                    font_size=12
                ),
                splitline_opts=opts.SplitLineOpts(
                    is_show=True,
                    linestyle_opts=opts.LineStyleOpts(opacity=0.2)
                )
            ),
            yaxis_opts=opts.AxisOpts(
                type_="value",
                axislabel_opts=opts.LabelOpts(
                    formatter="{value} kW",
                    font_size=12
                ),
                splitline_opts=opts.SplitLineOpts(
                    is_show=True,
                    linestyle_opts=opts.LineStyleOpts(opacity=0.2)
                )
            ),
            tooltip_opts=opts.TooltipOpts(
                trigger="axis",
                axis_pointer_type="cross",
                background_color="rgba(255,255,255,0.9)",
                border_color="#ccc",
                border_width=1,
                textstyle_opts=opts.TextStyleOpts(color="#666"),
                formatter=JsCode(
                    """function(params) {
                        return '<div style="padding: 3px;">' +
                               '<strong>' + params[0].name + '</strong><br/>' +
                               '<span style="color:#FFB01D">●</span> ' +
                               'Production: ' + params[0].value.toFixed(2) + ' kW' +
                               '</div>';
                    }"""
                )
            ),
            datazoom_opts=[
                opts.DataZoomOpts(
                    range_start=0,
                    range_end=100
                ),
                opts.DataZoomOpts(
                    type_="inside"
                )
            ]
        )

        return solar_chart

    def get_price_color(self, level, is_best):
        """Get color based on price level and best window status"""
        if is_best:
            return "#2ecc71"  # Green for best window

        colors = {
            "VERY_CHEAP": "#27ae60",
            "CHEAP": "#2ecc71",
            "NORMAL": "#f1c40f",
            "EXPENSIVE": "#e67e22",
            "VERY_EXPENSIVE": "#e74c3c"
        }
        return colors.get(level, "#95a5a6")

    async def create_energy_visualization(self, hours_past=12, hours_future=24):
        """Create visualization of prices and solar production"""
        prices = await self.tibber.get_price_range(hours_past, hours_future)

        # Create charts
        page = Page(layout=Page.SimplePageLayout)

        if prices:
            best_window = self.find_cheapest_hours(prices, hours_needed=4)
            price_chart = self.create_price_chart(prices, best_window)
            page.add(price_chart)
            self.print_price_details(prices, best_window)

        # Optionally get solar forecast
        if self.solar_api_key:  # Only try if API key is configured
            solar_forecast = await self.get_solar_forecast()
            if solar_forecast:
                solar_chart = self.create_solar_chart(solar_forecast)
                if solar_chart:
                    page.add(solar_chart)

        # Save to HTML file
        page.render("energy_forecast.html")
        print(f"\nCharts have been saved to energy_forecast.html")

    def print_price_details(self, prices, best_window):
        """Print detailed price information"""
        print("\nDetailed Price Information:")
        print("=" * 50)
        now = datetime.now().astimezone()

        # Find absolute cheapest future price
        future_prices = [
            (datetime.fromisoformat(p['startsAt']).astimezone(), p)
            for p in prices
            if datetime.fromisoformat(p['startsAt']).astimezone() > now
        ]

        if future_prices:
            min_future_price = min(float(p[1]['total']) * 100 for p in future_prices)
            cheapest_future_times = [
                dt for dt, p in future_prices
                if float(p['total']) * 100 == min_future_price
            ]

            print(f"\n{Fore.CYAN}Cheapest Future Price Points:{Style.RESET_ALL}")
            print(f"Price: {min_future_price:.1f} cents/kWh")
            print("Times:", ", ".join(t.strftime('%H:%M') for t in cheapest_future_times))

        if best_window:
            print(f"\n{Fore.GREEN}Best Future Charging Window ({best_window['end_time'] - best_window['start_time']}):{Style.RESET_ALL}")
            print(f"Start: {best_window['start_time'].strftime('%H:%M')}")
            print(f"End: {best_window['end_time'].strftime('%H:%M')}")
            print(f"Average Price: {best_window['average_price']*100:.1f} cents/kWh")
            print(f"Price Levels: {', '.join(best_window['price_levels'])}")

        print("\nAll Prices (Past prices in gray):")
        print("-" * 50)

        best_start = best_window['start_time'] if best_window else None
        best_end = best_window['end_time'] if best_window else None

        # Sort prices by time
        sorted_prices = sorted(
            [(datetime.fromisoformat(p['startsAt']).astimezone(), p)
             for p in prices]
        )

        for dt, price_data in sorted_prices:
            price = price_data['total'] * 100
            level = price_data.get('level', 'UNKNOWN')
            is_future = dt > now
            is_best = best_start and best_start <= dt <= best_end
            is_cheapest_future = is_future and future_prices and price == min_future_price

            time_str = dt.strftime('%H:%M')
            price_str = f"{price:.1f} cents/kWh"

            if not is_future:
                print(f"{Style.DIM}{time_str} - {price_str} ({level}){Style.RESET_ALL}")
            elif is_cheapest_future:
                print(f"{Fore.CYAN}{time_str} - {price_str} ({level}) ← CHEAPEST FUTURE{Style.RESET_ALL}")
            elif is_best:
                print(f"{Fore.GREEN}{time_str} - {price_str} ({level}) ← BEST WINDOW{Style.RESET_ALL}")
            else:
                print(f"{time_str} - {price_str} ({level})")

    def find_cheapest_hours(self, prices, hours_needed=4):
        """Find the cheapest consecutive hours in the future"""
        if not prices or len(prices) < hours_needed:
            return None

        now = datetime.now().astimezone()

        # Convert to list of (time, price, level) tuples, but only consider future times
        price_times = [(
            datetime.fromisoformat(p['startsAt']).astimezone(),
            p['total'],
            p.get('level', 'UNKNOWN')
        ) for p in prices if datetime.fromisoformat(p['startsAt']).astimezone() > now]

        if not price_times:
            return None

        # Sort by time
        price_times.sort()

        # Find cheapest window
        min_avg = float('inf')
        best_start = None
        best_levels = None

        for i in range(len(price_times) - hours_needed + 1):
            window = price_times[i:i + hours_needed]
            avg_price = sum(price for _, price, _ in window) / hours_needed

            if avg_price < min_avg:
                min_avg = avg_price
                best_start = window[0][0]
                best_levels = [level for _, _, level in window]

        if best_start:
            return {
                'start_time': best_start,
                'end_time': best_start + timedelta(hours=hours_needed),
                'average_price': min_avg,
                'price_levels': best_levels
            }
        return None

async def main():
    optimizer = EnergyOptimizer()

    print(f"\n{Fore.CYAN}Energy Optimization Report{Style.RESET_ALL}")
    print("=" * 50)

    await optimizer.create_energy_visualization()

if __name__ == "__main__":
    asyncio.run(main())