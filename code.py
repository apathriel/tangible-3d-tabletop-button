import time
import board
import wifi
import socketpool
from digitalio import DigitalInOut, Direction, Pull
import os

# WiFi Configuration
WIFI_SSID = os.getenv("WIFI_SSID")
WIFI_PASSWORD = os.getenv("WIFI_PASSWORD")
PC_IP = os.getenv("PC_IP")
PORT = os.getenv("PORT", 5000)

led = DigitalInOut(board.LED)
led.direction = Direction.OUTPUT

def pad4(s):
    """Pad bytes to next multiple of 4 bytes (OSC requirement)"""
    return s + (b'\x00' * ((4 - (len(s) % 4)) % 4))

def build_osc_message(address, *args):
    """
    Build a minimal OSC message.
    Only supports integer arguments for simplicity.
    """
    msg = pad4(address.encode('utf-8'))
    # Build type tag string
    type_tags = ',' + ''.join('i' for _ in args)
    msg += pad4(type_tags.encode('utf-8'))
    # Add arguments as 32-bit big-endian signed integers
    for arg in args:
        msg += int(arg).to_bytes(4, 'big', signed=True)
    return msg

def test_connectivity():
    """Test basic network connectivity"""
    print(f"ESP32 IP: {wifi.radio.ipv4_address}")
    print(f"Gateway: {wifi.radio.ipv4_gateway}")
    print(f"Subnet: {wifi.radio.ipv4_subnet}")
    print(f"Target PC: {PC_IP}:{PORT}")
    # Simple subnet check by comparing first 3 octets
    esp_parts = str(wifi.radio.ipv4_address).split('.')
    pc_parts = PC_IP.split('.')
    same_subnet = esp_parts[:3] == pc_parts[:3]
    print(f"Likely same subnet: {same_subnet}")

def ping_test():
    """Simple connectivity test"""
    try:
        pool = socketpool.SocketPool(wifi.radio)
        sock = pool.socket(pool.AF_INET, pool.SOCK_DGRAM)
        sock.settimeout(2.0)
        # Send test packet
        test_msg = b"PING_TEST"
        sock.sendto(test_msg, (PC_IP, PORT))
        print("✓ Test packet sent successfully")
        sock.close()
        return True
    except Exception as e:
        print(f"✗ Connectivity test failed: {e}")
        return False

# Button Setup
btn = DigitalInOut(board.A0)
btn.direction = Direction.INPUT
btn.pull = Pull.UP

print("Connecting to WiFi...")
wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
print(f"Connected! ESP32 IP: {wifi.radio.ipv4_address}")

# After wifi.radio.connect(...)
if wifi.radio.ipv4_address:
    led.value = True  # LED ON = WiFi connected
else:
    # Blink LED if not connected
    for _ in range(10):
        led.value = not led.value
        time.sleep(0.2)
    led.value = False

# Run diagnostics
test_connectivity()
ping_test()

pool = socketpool.SocketPool(wifi.radio)
sock = pool.socket(pool.AF_INET, pool.SOCK_DGRAM)

print("Ready! Press button...")
press_count = 0
prev_btn_state = True  # Assume button is not pressed at start (HIGH)

while True:
    curr_btn_state = btn.value  # True if not pressed, False if pressed

    # Detect button press (transition from not pressed to pressed)
    if prev_btn_state and not curr_btn_state:
        press_count += 1
        print(f"Button press #{press_count}")
        try:
            osc_msg = build_osc_message('/button/press', press_count)
            sock.sendto(osc_msg, (PC_IP, PORT))
            print("✓ OSC UDP packet sent for press!")
        except Exception as e:
            print(f"✗ Error sending OSC UDP packet on button press: {e}")

    # Detect button release (transition from pressed to not pressed)
    if not prev_btn_state and curr_btn_state:
        print("Button released")
        try:
            osc_msg = build_osc_message('/button/release', press_count)
            sock.sendto(osc_msg, (PC_IP, PORT))
            print("✓ OSC UDP packet sent for release!")
        except Exception as e:
            print(f"✗ Error: {e}")
        time.sleep(0.2)  # Debounce after release

    prev_btn_state = curr_btn_state
    time.sleep(0.05)
 # type: ignore