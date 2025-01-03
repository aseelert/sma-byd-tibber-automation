import argparse
from pymodbus.client import ModbusTcpClient
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)

def read_registers(client, register_addresses, range_value=None):
    for address in register_addresses:
        if range_value:
            start_address = max(0, address - range_value)
            end_address = address + range_value
            for addr in range(start_address, end_address + 1):
                read_register(client, addr)
        else:
            read_register(client, address)

def read_register(client, address):
    response = client.read_holding_registers(
        address=address,
        count=2,  # Read two registers
        slave=3   # Replace '3' with your inverter's Modbus unit ID
    )
    if response.isError():
        print(f"Error reading register {address}: {response}")
    else:
        # Assuming the first value is 0 and the second is the actual value
        print(f"Register {address} values: {response.registers}")

def main():
    parser = argparse.ArgumentParser(description='Modbus register reader.')
    parser.add_argument('-re', '--register', nargs='+', type=int, help='Register addresses to read')
    parser.add_argument('-ra', '--range', type=int, help='Range to read around a specific register')

    args = parser.parse_args()

    # Create Modbus client
    client = ModbusTcpClient('192.168.178.57', port=502)  # Replace with your inverter's IP

    try:
        # Connect to the client
        client.connect()

        if args.register:
            read_registers(client, args.register, args.range)

    except Exception as e:
        print(f"Error: {e}")

    finally:
        # Close the connection
        client.close()

if __name__ == "__main__":
    main()
