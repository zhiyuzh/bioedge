import smbus2
import time

# Create an SMBus instance
bus = smbus2.SMBus(1)

# GY-302 / BH1750 addresses
SENSOR1_ADDR = 0x23
SENSOR2_ADDR = 0x5C

# High resolution mode
CONTINUOUS_HIGH_RES_MODE = 0x10

def read_light(address):
    try:
        data = bus.read_i2c_block_data(address, CONTINUOUS_HIGH_RES_MODE, 2)

        lux = ((data[0] << 8) | data[1]) / 1.2

        return lux

    except Exception as e:
        print(f"Error reading {hex(address)}: {e}")
        return None


print("Starting GY-302 readings...")

try:
    while True:

        lux1 = read_light(SENSOR1_ADDR)
        lux2 = read_light(SENSOR2_ADDR)

        if lux1 is not None and lux2 is not None:
            print(f"Sensor 1: {lux1:.2f} Lux, Sensor 2: {lux2:.2f} Lux")

        time.sleep(1)

except KeyboardInterrupt:
    print("\nProgram stopped by user.")