"""
CircuitPython WiFi Button Controller
===================================
Sends OSC messages over WiFi when a button is pressed/released.
Also sends a handshake message on startup to announce device presence.

Hardware Requirements:
- ESP32-S2/S3 board with WiFi capability
- Button connected to pin A0 (with internal pull-up)
- Built-in LED for status indication

Configuration:
- Set WiFi credentials, device ID, and target PC IP in settings.toml
- Ensure target PC is listening on the specified UDP port

OSC Messages Sent:
- /button/handshake/<device_id> (on startup)
- /button/press (on button press)
- /button/release (on button release)
"""

import time
import board
import wifi
import socketpool
from digitalio import DigitalInOut, Direction, Pull
import os
import busio    
import adafruit_drv2605

# WiFi Configuration
WIFI_SSID = os.getenv("WIFI_SSID")
WIFI_PASSWORD = os.getenv("WIFI_PASSWORD")
PC_IP = os.getenv("PC_IP")
PORT = int(os.getenv("PORT", 5000))
DEVICE_ID = os.getenv("DEVICE_ID", "unknown_device")

# Validate required environment variables
if not WIFI_SSID:
    raise ValueError("WIFI_SSID environment variable is required")
if not WIFI_PASSWORD:
    raise ValueError("WIFI_PASSWORD environment variable is required")
if not PC_IP:
    raise ValueError("PC_IP environment variable is required")

print(f"Configuration loaded - Target: {PC_IP}:{PORT}")

# Led Setup
# led = DigitalInOut(board.LED)
# led.direction = Direction.OUTPUT

""" def blink_led(times, delay=0.1):
    for _ in range(times):
        led.value = True
        time.sleep(delay)
        led.value = False
        time.sleep(delay) """

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

def send_handshake(socket):
    """Send handshake message to announce device startup"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Send handshake message for Unity GameObject mapping
            handshake_address = f'/button/handshake'
            osc_msg = build_osc_message(handshake_address, int(DEVICE_ID))
            socket.sendto(osc_msg, (PC_IP, PORT))
            print(f"✓ Handshake sent successfully (attempt {attempt + 1})")
            print(f"  OSC Address: {handshake_address}")
            # blink_led(3, 0.1)  # 3 quick blinks to indicate handshake sent
            return True
        except Exception as e:
            print(f"✗ Handshake failed (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)  # Wait before retry
    
    print("✗ Failed to send handshake after all attempts")
    # blink_led(5, 0.2)  # 5 slow blinks to indicate handshake failure
    return False

# Button Setup
btn = DigitalInOut(board.A0)
btn.direction = Direction.INPUT
btn.pull = Pull.UP

# Haptic Setup
i2c = board.STEMMA_I2C()

drv = adafruit_drv2605.DRV2605(i2c)

drv.use_ERM()

drv.sequence[0] = adafruit_drv2605.Effect(1)

drv.play()  # Test haptic motor on startup

def connect_wifi():
    """Connect to WiFi with retry logic"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"Connecting to WiFi... (attempt {attempt + 1})")
            wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
            print(f"Connected! ESP32 IP: {wifi.radio.ipv4_address}")
            # led.value = True  # LED ON = WiFi connected
            return True
        except Exception as e:
            print(f"WiFi connection failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                # Blink LED if connection failed
                """ for _ in range(10):
                    led.value = not led.value
                    time.sleep(0.2)
                led.value = False
                return False """
    return False

# Connect to WiFi
if not connect_wifi():
    print("Failed to connect to WiFi. Check credentials and try again.")
    # Could add a reset or retry loop here

pool = socketpool.SocketPool(wifi.radio)
sock = pool.socket(pool.AF_INET, pool.SOCK_DGRAM)

# Send handshake message to announce device startup
print("Sending startup handshake...")
send_handshake(sock)

print("Ready! Press button...")
prev_btn_state = True  # Assume button is not pressed at start (HIGH)

while True:
    curr_btn_state = btn.value  # True if not pressed, False if pressed

    # Detect button press (transition from not pressed to pressed)
    if prev_btn_state and not curr_btn_state:
        print("Button pressed")
        try:
            osc_msg = build_osc_message('/button/press')
            debug_msg = "Button pressed"
            drv.play()  # Trigger haptic motor on press
            sock.sendto(osc_msg, (PC_IP, PORT))
            print("✓ OSC UDP packet sent for press!")
        except Exception as e:
            print(f"✗ Error sending OSC UDP packet on button press: {e}")

    # Detect button release (transition from pressed to not pressed)
    if not prev_btn_state and curr_btn_state:
        print("Button released")
        try:
            osc_msg = build_osc_message('/button/release')
            debug_msg = "Button released"
            sock.sendto(osc_msg, (PC_IP, PORT))
            print("✓ OSC UDP packet sent for release!")
        except Exception as e:
            print(f"✗ Error: {e}")
        time.sleep(0.2)  # Debounce after release

    prev_btn_state = curr_btn_state
    time.sleep(0.05)
 # type: ignore