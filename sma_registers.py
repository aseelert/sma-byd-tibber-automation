from dataclasses import dataclass
from enum import Enum
from typing import Optional

class RegisterFormat(Enum):
    RAW = "RAW"     # Raw register value
    DT = "DT"       # Date/Time format
    ENUM = "ENUM"   # Enumerated value
    FIX0 = "FIX0"   # No decimal places
    FIX1 = "FIX1"   # 1 decimal place
    FIX2 = "FIX2"   # 2 decimal places
    FIX3 = "FIX3"   # 3 decimal places

class RegisterType(Enum):
    U16 = "U16"     # Unsigned 16-bit integer
    S16 = "S16"     # Signed 16-bit integer
    U32 = "U32"     # Unsigned 32-bit integer
    S32 = "S32"     # Signed 32-bit integer
    U64 = "U64"     # Unsigned 64-bit integer
    S64 = "S64"     # Signed 64-bit integer
    STR = "STR"     # String value

@dataclass
class ModbusRegister:
    address: int
    count: int
    type: RegisterType
    format: RegisterFormat
    description: str
    unit: Optional[str] = None
    scale: Optional[float] = None

# SMA Sunny Tripower 6.0 SE with Storage Package Modbus Register Map
SMA_REGISTERS = {
    # Grid Measurements
    "grid_power":               ModbusRegister(30867, 2, RegisterType.S32, RegisterFormat.FIX0, "Grid power (positive = feed-in, negative = draw)", "W"),
    "grid_voltage_l1":          ModbusRegister(30783, 2, RegisterType.U32, RegisterFormat.FIX2, "Grid voltage L1", "V", 0.01),
    "grid_voltage_l2":          ModbusRegister(30785, 2, RegisterType.U32, RegisterFormat.FIX2, "Grid voltage L2", "V", 0.01),
    "grid_voltage_l3":          ModbusRegister(30787, 2, RegisterType.U32, RegisterFormat.FIX2, "Grid voltage L3", "V", 0.01),
    "grid_current_l1":          ModbusRegister(30977, 2, RegisterType.S32, RegisterFormat.FIX3, "Grid current L1", "A", 0.001),
    "grid_current_l2":          ModbusRegister(30979, 2, RegisterType.S32, RegisterFormat.FIX3, "Grid current L2", "A", 0.001),
    "grid_current_l3":          ModbusRegister(30981, 2, RegisterType.S32, RegisterFormat.FIX3, "Grid current L3", "A", 0.001),
    "grid_frequency":           ModbusRegister(30803, 2, RegisterType.U32, RegisterFormat.FIX2, "Grid frequency", "Hz", 0.01),

    # Battery Measurements
    "battery_voltage":          ModbusRegister(30843, 2, RegisterType.U32, RegisterFormat.FIX2, "Battery voltage", "V", 0.01),
    "battery_current":          ModbusRegister(30845, 2, RegisterType.S32, RegisterFormat.FIX2, "Battery current", "A", 0.01),
    "battery_power":            ModbusRegister(30847, 2, RegisterType.S32, RegisterFormat.FIX0, "Battery power (positive = charging, negative = discharging)", "W"),
    "battery_soc":              ModbusRegister(30845, 2, RegisterType.U32, RegisterFormat.FIX0, "Battery state of charge", "%"),
    "battery_temperature":       ModbusRegister(30851, 2, RegisterType.S32, RegisterFormat.FIX1, "Battery temperature", "°C", 0.1),
    "battery_status":           ModbusRegister(30955, 2, RegisterType.U32, RegisterFormat.ENUM, "Battery operating status"),

    # Battery Control (Holding Registers)
    "battery_control_mode":     ModbusRegister(40151, 2, RegisterType.U32, RegisterFormat.ENUM, "Battery operation mode control"),
    "battery_power_control":    ModbusRegister(40149, 2, RegisterType.S32, RegisterFormat.FIX0, "Battery power setpoint", "W"),

    # DC (PV) Input Measurements
    "dc_power_a":              ModbusRegister(30773, 2, RegisterType.S32, RegisterFormat.FIX0, "DC Power MPP1", "W"),
    "dc_voltage_a":            ModbusRegister(30771, 2, RegisterType.U32, RegisterFormat.FIX2, "DC Voltage MPP1", "V", 0.01),
    "dc_current_a":            ModbusRegister(30769, 2, RegisterType.S32, RegisterFormat.FIX3, "DC Current MPP1", "A", 0.001),
    "dc_power_b":              ModbusRegister(30961, 2, RegisterType.S32, RegisterFormat.FIX0, "DC Power MPP2", "W"),
    "dc_voltage_b":            ModbusRegister(30959, 2, RegisterType.U32, RegisterFormat.FIX2, "DC Voltage MPP2", "V", 0.01),
    "dc_current_b":            ModbusRegister(30957, 2, RegisterType.S32, RegisterFormat.FIX3, "DC Current MPP2", "A", 0.001),

    # Energy Counters
    "total_yield":             ModbusRegister(30529, 4, RegisterType.U64, RegisterFormat.FIX0, "Total yield", "Wh"),
    "daily_yield":             ModbusRegister(30535, 2, RegisterType.U32, RegisterFormat.FIX0, "Daily yield", "Wh"),
    "battery_charge_counter":   ModbusRegister(30597, 4, RegisterType.U64, RegisterFormat.FIX0, "Total energy charged to battery", "Wh"),
    "battery_discharge_counter":ModbusRegister(30599, 4, RegisterType.U64, RegisterFormat.FIX0, "Total energy discharged from battery", "Wh"),
    "operating_time":          ModbusRegister(30541, 4, RegisterType.U64, RegisterFormat.FIX0, "Operating time", "s"),
    "feed_in_time":            ModbusRegister(30543, 4, RegisterType.U64, RegisterFormat.FIX0, "Feed-in time", "s"),

    # Device Information
    "device_status":           ModbusRegister(30201, 2, RegisterType.U32, RegisterFormat.ENUM, "Device Status"),
    "device_class":            ModbusRegister(30051, 2, RegisterType.U32, RegisterFormat.ENUM, "Device class"),
    "error_code":              ModbusRegister(30953, 2, RegisterType.U32, RegisterFormat.FIX0, "Error code"),
    "software_version":        ModbusRegister(30053, 2, RegisterType.U32, RegisterFormat.FIX0, "Software version"),
    "serial_number":           ModbusRegister(30057, 2, RegisterType.U32, RegisterFormat.RAW, "Serial number"),

    # Temperature
    "internal_temperature":    ModbusRegister(30953, 2, RegisterType.S32, RegisterFormat.FIX1, "Device temperature", "°C", 0.1),

    # Power Flow Measurements
    "house_consumption":        ModbusRegister(30865, 2, RegisterType.S32, RegisterFormat.FIX0, "House total power consumption", "W"),
    "pv_total_power":          ModbusRegister(30775, 2, RegisterType.S32, RegisterFormat.FIX0, "Total PV power generation", "W"),
    "self_consumption":         ModbusRegister(30867, 2, RegisterType.S32, RegisterFormat.FIX0, "Current self-consumption", "W"),
    "grid_feed_in":            ModbusRegister(30869, 2, RegisterType.S32, RegisterFormat.FIX0, "Grid feed-in power", "W"),
    "grid_draw":               ModbusRegister(30871, 2, RegisterType.S32, RegisterFormat.FIX0, "Grid power draw", "W"),

    # Battery Power Flow
    "battery_charge_power":     ModbusRegister(30847, 2, RegisterType.S32, RegisterFormat.FIX0, "Battery charging power", "W"),
    "battery_discharge_power":  ModbusRegister(30849, 2, RegisterType.S32, RegisterFormat.FIX0, "Battery discharging power", "W"),
    "battery_charge_source":    ModbusRegister(30853, 2, RegisterType.U32, RegisterFormat.ENUM, "Battery charging source (PV/Grid)"),
    "battery_charge_mode":      ModbusRegister(30855, 2, RegisterType.U32, RegisterFormat.ENUM, "Battery charging mode"),

    # Performance Metrics
    "autarky_ratio":           ModbusRegister(30873, 2, RegisterType.U32, RegisterFormat.FIX1, "Current autarky ratio", "%", 0.1),
    "self_consumption_ratio":   ModbusRegister(30875, 2, RegisterType.U32, RegisterFormat.FIX1, "Self-consumption ratio", "%", 0.1),
    "battery_efficiency":       ModbusRegister(30877, 2, RegisterType.U32, RegisterFormat.FIX1, "Battery round-trip efficiency", "%", 0.1),

    # Daily Energy Statistics
    "daily_house_consumption":  ModbusRegister(30595, 2, RegisterType.U32, RegisterFormat.FIX0, "Daily house consumption", "Wh"),
    "daily_self_consumption":   ModbusRegister(30597, 2, RegisterType.U32, RegisterFormat.FIX0, "Daily self-consumption", "Wh"),
    "daily_grid_feed_in":      ModbusRegister(30599, 2, RegisterType.U32, RegisterFormat.FIX0, "Daily grid feed-in", "Wh"),
    "daily_grid_draw":         ModbusRegister(30601, 2, RegisterType.U32, RegisterFormat.FIX0, "Daily grid draw", "Wh"),
    "daily_battery_charge":     ModbusRegister(30603, 2, RegisterType.U32, RegisterFormat.FIX0, "Daily battery charge", "Wh"),
    "daily_battery_discharge":  ModbusRegister(30605, 2, RegisterType.U32, RegisterFormat.FIX0, "Daily battery discharge", "Wh"),

    # AC Output Measurements
    "ac_power":               ModbusRegister(30775, 2, RegisterType.S32, RegisterFormat.FIX0, "Total AC active power", "W"),
    "ac_power_l1":           ModbusRegister(30777, 2, RegisterType.S32, RegisterFormat.FIX0, "AC active power L1", "W"),
    "ac_power_l2":           ModbusRegister(30779, 2, RegisterType.S32, RegisterFormat.FIX0, "AC active power L2", "W"),
    "ac_power_l3":           ModbusRegister(30781, 2, RegisterType.S32, RegisterFormat.FIX0, "AC active power L3", "W"),

    # AC Voltage Measurements
    "ac_voltage_l1":         ModbusRegister(30783, 2, RegisterType.U32, RegisterFormat.FIX2, "AC voltage L1", "V", 0.01),
    "ac_voltage_l2":         ModbusRegister(30785, 2, RegisterType.U32, RegisterFormat.FIX2, "AC voltage L2", "V", 0.01),
    "ac_voltage_l3":         ModbusRegister(30787, 2, RegisterType.U32, RegisterFormat.FIX2, "AC voltage L3", "V", 0.01),

    # AC Current Measurements
    "ac_current_l1":         ModbusRegister(30977, 2, RegisterType.S32, RegisterFormat.FIX3, "AC current L1", "A", 0.001),
    "ac_current_l2":         ModbusRegister(30979, 2, RegisterType.S32, RegisterFormat.FIX3, "AC current L2", "A", 0.001),
    "ac_current_l3":         ModbusRegister(30981, 2, RegisterType.S32, RegisterFormat.FIX3, "AC current L3", "A", 0.001),

    # AC Quality Measurements
    "ac_frequency":          ModbusRegister(30803, 2, RegisterType.U32, RegisterFormat.FIX2, "AC grid frequency", "Hz", 0.01),
    "ac_power_factor":       ModbusRegister(30805, 2, RegisterType.S32, RegisterFormat.FIX3, "Power factor", "", 0.001),
    "ac_apparent_power":     ModbusRegister(30807, 2, RegisterType.S32, RegisterFormat.FIX0, "Apparent power", "VA"),
    "ac_reactive_power":     ModbusRegister(30809, 2, RegisterType.S32, RegisterFormat.FIX0, "Reactive power", "var"),

    # AC Energy Counters
    "ac_energy_total":       ModbusRegister(30513, 4, RegisterType.U64, RegisterFormat.FIX0, "Total AC energy feed-in", "Wh"),
    "ac_energy_today":       ModbusRegister(30535, 2, RegisterType.U32, RegisterFormat.FIX0, "Today's AC energy feed-in", "Wh"),
    "ac_energy_yesterday":   ModbusRegister(30537, 2, RegisterType.U32, RegisterFormat.FIX0, "Yesterday's AC energy feed-in", "Wh"),
}

# Status/Mode Enumerations
DEVICE_STATUS = {
    35: "Fault",
    303: "Off",
    307: "OK",
    455: "Warning"
}

BATTERY_STATUS = {
    2291: "Charging",
    2292: "Discharging",
    2293: "Standby",
    2294: "Grid",
    2295: "Backup power",
    2296: "External control"
}

RELAY_STATUS = {
    51: "Open",
    311: "Closed"
}

BATTERY_MODES = {
    802: "Manual",      # Manual power control
    803: "Normal"       # Automatic operation
}

# Add new status enumerations
BATTERY_CHARGE_SOURCE = {
    1: "PV Direct",
    2: "Grid",
    3: "PV + Grid"
}

BATTERY_CHARGE_MODE = {
    1: "Normal Charging",
    2: "Fast Charging",
    3: "Balancing",
    4: "Maintenance",
    5: "Backup Reserve",
    6: "Shadow Management"
}

POWER_SOURCE = {
    1: "PV Only",
    2: "Battery Only",
    3: "PV + Battery",
    4: "Grid Only",
    5: "Grid + PV",
    6: "Grid + Battery",
    7: "Grid + PV + Battery"
}