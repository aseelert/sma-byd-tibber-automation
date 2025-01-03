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
    # Global Power Control
    "operation_health":        ModbusRegister(30201, 2, RegisterType.U32, RegisterFormat.ENUM, "Operating condition", ""),  # Condition/Status of device
    "operation_mode":          ModbusRegister(40029, 2, RegisterType.U32, RegisterFormat.ENUM, "Operating mode", ""),      # Operating mode of device
    "grid_relay_status":       ModbusRegister(30217, 2, RegisterType.U32, RegisterFormat.ENUM, "Grid relay/contactor status", ""),

    # Current Power Values
    "total_dc_power":          ModbusRegister(30773, 2, RegisterType.S32, RegisterFormat.FIX0, "DC power input (sum of both MPP)", "W"),
    "total_ac_power":          ModbusRegister(30775, 2, RegisterType.S32, RegisterFormat.FIX0, "AC power output (sum of all phases)", "W"),
    "total_ac_apparent":       ModbusRegister(30813, 2, RegisterType.S32, RegisterFormat.FIX0, "AC apparent power (sum of all phases)", "VA"),
    "total_ac_reactive":       ModbusRegister(30805, 2, RegisterType.S32, RegisterFormat.FIX0, "AC reactive power (sum of all phases)", "var"),

    # DC Values per MPP Tracker
    "dc1_voltage":             ModbusRegister(30771, 2, RegisterType.U32, RegisterFormat.FIX2, "DC voltage MPP1", "V", 0.01),
    "dc1_current":             ModbusRegister(30769, 2, RegisterType.S32, RegisterFormat.FIX3, "DC current MPP1", "A", 0.001),
    "dc1_power":               ModbusRegister(30773, 2, RegisterType.S32, RegisterFormat.FIX0, "DC power MPP1", "W"),
    "dc2_voltage":             ModbusRegister(30959, 2, RegisterType.U32, RegisterFormat.FIX2, "DC voltage MPP2", "V", 0.01),
    "dc2_current":             ModbusRegister(30957, 2, RegisterType.S32, RegisterFormat.FIX3, "DC current MPP2", "A", 0.001),
    "dc2_power":               ModbusRegister(30961, 2, RegisterType.S32, RegisterFormat.FIX0, "DC power MPP2", "W"),

    # AC Values per Phase
    "ac_l1_voltage":           ModbusRegister(30783, 2, RegisterType.U32, RegisterFormat.FIX2, "AC voltage phase L1", "V", 0.01),
    "ac_l2_voltage":           ModbusRegister(30785, 2, RegisterType.U32, RegisterFormat.FIX2, "AC voltage phase L2", "V", 0.01),
    "ac_l3_voltage":           ModbusRegister(30787, 2, RegisterType.U32, RegisterFormat.FIX2, "AC voltage phase L3", "V", 0.01),
    "ac_l1_current":           ModbusRegister(30977, 2, RegisterType.S32, RegisterFormat.FIX3, "AC current phase L1", "A", 0.001),
    "ac_l2_current":           ModbusRegister(30979, 2, RegisterType.S32, RegisterFormat.FIX3, "AC current phase L2", "A", 0.001),
    "ac_l3_current":           ModbusRegister(30981, 2, RegisterType.S32, RegisterFormat.FIX3, "AC current phase L3", "A", 0.001),
    "ac_l1_power":             ModbusRegister(30777, 2, RegisterType.S32, RegisterFormat.FIX0, "AC active power phase L1", "W"),
    "ac_l2_power":             ModbusRegister(30779, 2, RegisterType.S32, RegisterFormat.FIX0, "AC active power phase L2", "W"),
    "ac_l3_power":             ModbusRegister(30781, 2, RegisterType.S32, RegisterFormat.FIX0, "AC active power phase L3", "W"),

    # Grid Measurements
    "grid_frequency":          ModbusRegister(30803, 2, RegisterType.U32, RegisterFormat.FIX2, "Grid frequency", "Hz", 0.01),
    "displacement_cos_phi":    ModbusRegister(30807, 2, RegisterType.S32, RegisterFormat.FIX3, "Displacement power factor", "", 0.001),

    # Energy Meters
    "total_yield":             ModbusRegister(30529, 4, RegisterType.U64, RegisterFormat.FIX0, "Total energy yield", "Wh"),
    "daily_yield":             ModbusRegister(30535, 2, RegisterType.U32, RegisterFormat.FIX0, "Day yield", "Wh"),
    "operating_time":          ModbusRegister(30541, 4, RegisterType.U64, RegisterFormat.FIX0, "Feed-in time", "s"),

    # Battery System (Storage Interface)
    "battery_soc":             ModbusRegister(30845, 2, RegisterType.U32, RegisterFormat.FIX0, "Current battery state of charge", "%"),
    "battery_charging_status": ModbusRegister(30955, 2, RegisterType.U32, RegisterFormat.ENUM, "Battery charging status", ""),
    "battery_operating_status":ModbusRegister(30957, 2, RegisterType.U32, RegisterFormat.ENUM, "Battery operating mode", ""),
    "battery_power":           ModbusRegister(30847, 2, RegisterType.S32, RegisterFormat.FIX0, "Current battery charging power", "W"),

    # Device Information
    "device_class":            ModbusRegister(30051, 2, RegisterType.U32, RegisterFormat.ENUM, "Device class", ""),
    "device_type":             ModbusRegister(30053, 2, RegisterType.U32, RegisterFormat.FIX0, "Device type", ""),
    "device_name":             ModbusRegister(40021, 16, RegisterType.STR, RegisterFormat.RAW, "Device name", ""),
    "serial_number":           ModbusRegister(30057, 2, RegisterType.U32, RegisterFormat.RAW, "Serial number", ""),
    "sw_version":              ModbusRegister(30059, 2, RegisterType.U32, RegisterFormat.FIX0, "Software package", ""),
}

# Updated status enumerations based on documentation
DEVICE_STATUS = {
    35: "Fault",
    303: "Off",
    307: "Ok",
    455: "Warning",
    1392: "Battery Charging",
    1393: "Battery Discharging",
    1394: "Battery Standby",
    2119: "Battery Protection Mode",
    16777213: "No Communication"
}

GRID_RELAY_STATUS = {
    51: "Open",
    311: "Closed",
    1392: "Battery Charging",
    1393: "Battery Discharging",
    1394: "Battery Standby"
}

BATTERY_CHARGING_STATUS = {
    2291: "Charging",
    2292: "Discharging",
    2293: "Standby",
    2294: "Grid",
    2295: "Backup Power",
    2303: "Fault",
    2304: "Service"
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