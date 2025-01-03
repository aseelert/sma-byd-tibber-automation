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

# SMA Sunny Island Modbus Register Map
SMA_REGISTERS = {
    # Grid Measurements
    "grid_power":               ModbusRegister(30865, 2, RegisterType.S32, RegisterFormat.FIX0, "Grid power (positive = feed-in, negative = consumption)", "W"),

    # Battery Measurements
    "battery_voltage":          ModbusRegister(30843, 2, RegisterType.U32, RegisterFormat.FIX2, "Battery voltage", "V", 0.01),
    "battery_current":          ModbusRegister(30843, 2, RegisterType.S32, RegisterFormat.FIX2, "Battery current", "A", 0.01),
    "battery_power":           ModbusRegister(30845, 2, RegisterType.S32, RegisterFormat.FIX0, "Battery charging power (positive = charging)", "W"),
    "battery_soc":             ModbusRegister(30845, 2, RegisterType.U32, RegisterFormat.FIX0, "Battery state of charge", "%"),
    "battery_temperature":      ModbusRegister(30849, 2, RegisterType.S32, RegisterFormat.FIX1, "Battery temperature", "°C", 0.1),

    # House/Load Measurements
    "house_power":             ModbusRegister(30773, 2, RegisterType.S32, RegisterFormat.FIX0, "House power consumption", "W"),
    "load_power":              ModbusRegister(30775, 2, RegisterType.S32, RegisterFormat.FIX0, "Total load power", "W"),

    # Solar/PV Measurements
    "pv_power":                ModbusRegister(30775, 2, RegisterType.S32, RegisterFormat.FIX0, "Solar PV power generation", "W"),

    # Energy Counters
    "grid_feed_counter":       ModbusRegister(30513, 4, RegisterType.U64, RegisterFormat.FIX0, "Total energy fed to grid", "Wh"),
    "grid_consumption_counter": ModbusRegister(30521, 4, RegisterType.U64, RegisterFormat.FIX0, "Total energy consumed from grid", "Wh"),
    "battery_charge_counter":   ModbusRegister(30597, 4, RegisterType.U64, RegisterFormat.FIX0, "Total energy charged to battery", "Wh"),
    "battery_discharge_counter":ModbusRegister(30581, 4, RegisterType.U64, RegisterFormat.FIX0, "Total energy discharged from battery", "Wh"),

    # Status Registers
    "device_status":           ModbusRegister(30201, 2, RegisterType.U32, RegisterFormat.ENUM, "Device operating status"),
    "battery_operating_status": ModbusRegister(30955, 2, RegisterType.U32, RegisterFormat.ENUM, "Battery operating status"),
    "relay_status":            ModbusRegister(30957, 2, RegisterType.U32, RegisterFormat.ENUM, "Grid relay status"),

    # Control Registers (Holding Registers)
    "battery_control_mode":     ModbusRegister(40151, 2, RegisterType.U32, RegisterFormat.ENUM, "Battery operation mode control"),
    "battery_power_control":    ModbusRegister(40149, 2, RegisterType.S32, RegisterFormat.FIX0, "Battery power setpoint", "W"),

    # System Information
    "device_class":            ModbusRegister(30051, 2, RegisterType.U32, RegisterFormat.ENUM, "Device class identifier"),
    "software_version":        ModbusRegister(30053, 2, RegisterType.U32, RegisterFormat.FIX0, "Software version"),
    "serial_number":           ModbusRegister(30057, 2, RegisterType.U32, RegisterFormat.RAW, "Device serial number"),
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