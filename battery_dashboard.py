import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime, timedelta
from battery_controller import BatteryController, BatteryMode
import asyncio

class BatteryDashboard:
    def __init__(self, controller):
        self.controller = controller

    def render(self):
        st.set_page_config(layout="wide")
        st.title("Smart Energy Management System")

        # Get current status and analytics
        status = self.controller.get_system_status()
        analytics = self.controller.get_analytics()

        # System Overview
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric(
                "Battery Status",
                f"{status.battery.soc}%",
                f"{status.battery.power}W"
            )

        with col2:
            st.metric(
                "Current Price",
                f"{status.current_price:.3f}€/kWh",
                self.get_price_delta(status)
            )

        with col3:
            st.metric(
                "Solar Production",
                f"{status.pv_power}W",
                f"Using {self.get_self_consumption_ratio(status)}% locally"
            )

        with col4:
            st.metric(
                "Estimated Savings",
                f"{analytics['savings_estimate']:.2f}€ today"
            )

        # Control Panel
        st.sidebar.header("Control Panel")

        mode = st.sidebar.selectbox(
            "Battery Mode",
            [mode.name for mode in BatteryMode],
            index=status.battery.mode.value
        )

        if st.sidebar.button("Set Mode"):
            self.controller.set_battery_mode(BatteryMode[mode])

        charge_power = st.sidebar.slider(
            "Charge Power",
            1000, 5000, status.battery.target_power,
            step=100
        )

        if st.sidebar.button("Set Power"):
            self.controller.set_charge_power(charge_power)

        # Main Charts
        st.subheader("System Overview")
        fig = self.create_system_overview_chart(status)
        st.plotly_chart(fig, use_container_width=True)

        # Price Analysis
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Price Distribution")
            fig = self.create_price_distribution_chart()
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.subheader("Battery Usage")
            fig = self.create_battery_usage_chart()
            st.plotly_chart(fig, use_container_width=True)

        # System Log
        st.subheader("System Log")
        log_df = self.get_system_log()
        st.dataframe(log_df)

        # Add price prediction chart
        st.subheader("Price Prediction")
        pred_fig = self.create_price_prediction_chart()
        if pred_fig:
            st.plotly_chart(pred_fig, use_container_width=True)

        # Add configuration
        self.render_configuration()

        # Add pattern analysis
        patterns = asyncio.run(self.controller.analyze_price_patterns())
        if patterns:
            st.subheader("Price Patterns")
            col1, col2 = st.columns(2)

            with col1:
                st.write("Typical Cheap Hours:")
                st.write(", ".join(f"{h}:00" for h in patterns['cheap_hours']))
                st.write(f"Price Volatility: {patterns['price_volatility']:.3f}")

            with col2:
                st.write("Best Hours:")
                st.write(f"Cheapest Hour: {patterns['min_price_hour']}:00")
                st.write(f"Most Expensive Hour: {patterns['max_price_hour']}:00")

    def create_system_overview_chart(self, status):
        """Create main system overview chart"""
        df = pd.DataFrame(self.controller.state_history)

        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            subplot_titles=("Power Flow", "Prices & Battery Level")
        )

        # Power flow
        fig.add_trace(
            go.Scatter(
                x=df['timestamp'],
                y=df['pv_power'],
                name="Solar",
                fill='tozeroy',
                line=dict(color='yellow')
            ),
            row=1, col=1
        )

        fig.add_trace(
            go.Scatter(
                x=df['timestamp'],
                y=df['battery_power'],
                name="Battery",
                line=dict(color='green')
            ),
            row=1, col=1
        )

        # Prices and battery level
        fig.add_trace(
            go.Scatter(
                x=df['timestamp'],
                y=df['current_price'],
                name="Price",
                yaxis="y2",
                line=dict(color='blue')
            ),
            row=2, col=1
        )

        fig.add_trace(
            go.Scatter(
                x=df['timestamp'],
                y=df['battery_soc'],
                name="Battery %",
                yaxis="y3",
                line=dict(color='orange')
            ),
            row=2, col=1
        )

        return fig

    def get_system_log(self):
        """Get formatted system log for display"""
        df = pd.DataFrame(self.controller.state_history)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp', ascending=False)

        # Format columns for display
        df['battery_soc'] = df['battery_soc'].round(1).astype(str) + '%'
        df['current_price'] = df['current_price'].round(3).astype(str) + '€/kWh'
        df['pv_power'] = df['pv_power'].round(0).astype(str) + 'W'

        return df[['timestamp', 'battery_soc', 'battery_mode', 'current_price', 'pv_power', 'car_charging']]

    def create_price_prediction_chart(self):
        """Create price prediction visualization"""
        windows = asyncio.run(self.controller.predict_charging_windows())
        if not windows:
            return None

        fig = go.Figure()

        # Add price line
        prices = asyncio.run(self.controller.tibber.get_price_range(0, 24))
        df = pd.DataFrame(prices)
        df['datetime'] = pd.to_datetime(df['startsAt'])

        fig.add_trace(go.Scatter(
            x=df['datetime'],
            y=df['total'],
            name='Price',
            line=dict(color='blue')
        ))

        # Add predicted windows
        for i, window in enumerate(windows):
            fig.add_trace(go.Scatter(
                x=[window['start'], window['end']],
                y=[window['avg_price'], window['avg_price']],
                name=f'Window {i+1}',
                line=dict(
                    color=['green', 'yellow', 'orange'][i],
                    width=4,
                    dash='dash'
                ),
                hovertemplate=(
                    f"Window {i+1}<br>" +
                    "Start: %{x}<br>" +
                    "Price: %{y:.3f}€/kWh<br>" +
                    f"Score: {window['score']:.1f}"
                )
            ))

        fig.update_layout(
            title="Price Prediction and Charging Windows",
            xaxis_title="Time",
            yaxis_title="Price (€/kWh)",
            hovermode='x unified'
        )

        return fig

    def render_configuration(self):
        """Render configuration section"""
        st.sidebar.subheader("System Configuration")

        # Price thresholds
        st.sidebar.write("Price Thresholds (€/kWh)")
        very_cheap = st.sidebar.number_input(
            "Very Cheap",
            0.0, 1.0,
            self.controller.price_threshold_very_cheap,
            0.01
        )
        cheap = st.sidebar.number_input(
            "Cheap",
            0.0, 1.0,
            self.controller.price_threshold_cheap,
            0.01
        )

        # Battery settings
        st.sidebar.write("Battery Settings")
        min_soc = st.sidebar.slider(
            "Minimum SoC (%)",
            0, 50,
            int(self.controller.battery.min_soc)
        )
        max_soc = st.sidebar.slider(
            "Maximum SoC (%)",
            50, 100,
            int(self.controller.battery.max_soc)
        )

        # Charging strategy
        st.sidebar.write("Charging Strategy")
        min_charging_time = st.sidebar.slider(
            "Minimum Charging Time (hours)",
            1, 6,
            self.controller.min_charging_time
        )

        if st.sidebar.button("Save Configuration"):
            self.controller.price_threshold_very_cheap = very_cheap
            self.controller.price_threshold_cheap = cheap
            self.controller.battery.min_soc = min_soc
            self.controller.battery.max_soc = max_soc
            self.controller.min_charging_time = min_charging_time
            st.sidebar.success("Configuration saved!")