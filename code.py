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
import adafruit_drv2605

# ============================================================================
# CONFIGURATION MANAGEMENT
# ============================================================================

def load_configuration():
    """Load and validate configuration from environment variables"""
    config = {
        'WIFI_SSID': os.getenv("WIFI_SSID"),
        'WIFI_PASSWORD': os.getenv("WIFI_PASSWORD"),
        'PC_IP': os.getenv("PC_IP"),
        'PORT': int(os.getenv("PORT", 5000)),
        'LISTEN_PORT': int(os.getenv("LISTEN_PORT", 5001)),
        'DEVICE_ID': os.getenv("DEVICE_ID", "unknown_device")
    }
    
    # Validate required environment variables
    required_vars = ['WIFI_SSID', 'WIFI_PASSWORD', 'PC_IP']
    for var in required_vars:
        if not config[var]:
            raise ValueError(f"{var} environment variable is required")
    
    print(f"Configuration loaded - Target: {config['PC_IP']}:{config['PORT']}")
    return config

# ============================================================================
# HARDWARE INITIALIZATION
# ============================================================================

def setup_button():
    """Initialize button hardware"""
    btn = DigitalInOut(board.A0)
    btn.direction = Direction.INPUT
    btn.pull = Pull.UP
    return btn

def setup_haptic():
    """Initialize haptic motor hardware"""
    try:
        i2c = board.STEMMA_I2C()
        drv = adafruit_drv2605.DRV2605(i2c)
        drv.use_ERM()
        drv.sequence[0] = adafruit_drv2605.Effect(1)
        print("✓ Haptic motor initialized successfully")
        return drv
    except Exception as e:
        print(f"⚠ Haptic motor not available: {e}")
        return None

def connect_wifi(config):
    """Connect to WiFi with retry logic"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"Connecting to WiFi... (attempt {attempt + 1})")
            wifi.radio.connect(config['WIFI_SSID'], config['WIFI_PASSWORD'])
            esp32_ip = wifi.radio.ipv4_address
            print(f"Connected! ESP32 IP: {esp32_ip}")
            return esp32_ip
        except Exception as e:
            print(f"WiFi connection failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                print("✗ Failed to connect to WiFi after all attempts")
    return None

def setup_sockets(config):
    """Initialize UDP sockets for sending and receiving"""
    pool = socketpool.SocketPool(wifi.radio)
    
    # Sending socket
    send_sock = pool.socket(pool.AF_INET, pool.SOCK_DGRAM)
    
    # Receiving socket
    recv_sock = pool.socket(pool.AF_INET, pool.SOCK_DGRAM)
    recv_sock.settimeout(0.01)
    
    try:
        recv_sock.bind(('0.0.0.0', config['LISTEN_PORT']))
        print(f"✓ Listening for OSC messages on port {config['LISTEN_PORT']}")
    except Exception as e:
        print(f"✗ Failed to bind to port {config['LISTEN_PORT']}: {e}")
    
    return send_sock, recv_sock

def pad4(s):
    """Pad bytes to next multiple of 4 bytes (OSC requirement)"""
    return s + (b'\x00' * ((4 - (len(s) % 4)) % 4))

def build_osc_message(address, *args):
    """
    Build a minimal OSC message.
    Supports integer and string arguments.
    """
    msg = pad4(address.encode('utf-8'))
    
    # Build type tag string based on argument types
    type_tags = ','
    for arg in args:
        if isinstance(arg, str):
            type_tags += 's'  # string type
        elif isinstance(arg, int):
            type_tags += 'i'  # integer type
        else:
            # Convert other types to integers for compatibility
            type_tags += 'i'
    
    msg += pad4(type_tags.encode('utf-8'))
    
    # Add arguments based on their types
    for arg in args:
        if isinstance(arg, str):
            # String arguments need to be null-terminated and padded
            string_data = arg.encode('utf-8') + b'\x00'
            msg += pad4(string_data)
        elif isinstance(arg, int):
            # Integer arguments are 4-byte big-endian
            msg += arg.to_bytes(4, 'big', signed=True)
        else:
            # Convert other types to integers
            msg += int(arg).to_bytes(4, 'big', signed=True)
    
    return msg

def parse_osc_message(data):
    """
    Parse a simple OSC message to extract the address.
    Returns the OSC address string or None if parsing fails.
    """
    try:
        # Find the first null terminator for the address
        null_pos = data.find(b'\x00')
        if null_pos == -1:
            return None
        
        address = data[:null_pos].decode('utf-8')
        return address
    except:
        return None

# ============================================================================
# HARDWARE SETUP FUNCTIONS
# ============================================================================
    
def handle_incoming_osc(address, drv):
    """Handle incoming OSC messages and perform actions"""
    print(f"Received OSC: {address}")
    
    if address == "/haptic/play":
        if drv is not None:
            print("Triggering haptic motor...")
            drv.play()
        else:
            print("⚠ Haptic motor not available - skipping haptic feedback")
    else:
        print(f"Unknown OSC address: {address}")

# ============================================================================
# NETWORK DIAGNOSTIC FUNCTIONS
# ============================================================================

def test_connectivity(config):
    """Test basic network connectivity"""
    print(f"ESP32 IP: {wifi.radio.ipv4_address}")
    print(f"Gateway: {wifi.radio.ipv4_gateway}")
    print(f"Subnet: {wifi.radio.ipv4_subnet}")
    print(f"Target PC: {config['PC_IP']}:{config['PORT']}")
    # Simple subnet check by comparing first 3 octets
    esp_parts = str(wifi.radio.ipv4_address).split('.')
    pc_parts = config['PC_IP'].split('.')
    same_subnet = esp_parts[:3] == pc_parts[:3]
    print(f"Likely same subnet: {same_subnet}")

def ping_test(config):
    """Simple connectivity test"""
    try:
        pool = socketpool.SocketPool(wifi.radio)
        sock = pool.socket(pool.AF_INET, pool.SOCK_DGRAM)
        sock.settimeout(2.0)
        # Send test packet
        test_msg = b"PING_TEST"
        sock.sendto(test_msg, (config['PC_IP'], config['PORT']))
        print("✓ Test packet sent successfully")
        sock.close()
        return True
    except Exception as e:
        print(f"✗ Connectivity test failed: {e}")
        return False

def send_handshake(socket, config):
    """Send handshake message to announce device startup"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Send handshake message for Unity GameObject mapping
            handshake_address = f'/button/handshake'
            osc_msg = build_osc_message(handshake_address, int(config['DEVICE_ID']))
            socket.sendto(osc_msg, (config['PC_IP'], config['PORT']))
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

# ============================================================================
# EVENT HANDLING FUNCTIONS
# ============================================================================

def handle_button_events(btn, prev_btn_state, send_sock, config, drv, haptic_effect=1):
    """Handle button press and release events"""
    curr_btn_state = btn.value  # True if not pressed, False if pressed

    # Detect button press (transition from not pressed to pressed)
    if prev_btn_state and not curr_btn_state:
        print("Button pressed")
        try:
            osc_msg = build_osc_message('/button/press', 33)
            if drv is not None:
                drv.sequence[0] = adafruit_drv2605.Effect(haptic_effect)
                drv.play()  # Trigger haptic motor on press
            else:
                print("⚠ Haptic motor not available - skipping haptic feedback")
            send_sock.sendto(osc_msg, (config['PC_IP'], config['PORT']))
            print("✓ OSC UDP packet sent for press!")
        except Exception as e:
            print(f"✗ Error sending OSC UDP packet on button press: {e}")

    # Detect button release (transition from pressed to not pressed)
    if not prev_btn_state and curr_btn_state:
        print("Button released")
        try:
            osc_msg = build_osc_message('/button/release', "test")
            send_sock.sendto(osc_msg, (config['PC_IP'], config['PORT']))
            print("✓ OSC UDP packet sent for release!")
        except Exception as e:
            print(f"✗ Error: {e}")
        time.sleep(0.2)  # Debounce after release

    return curr_btn_state

def handle_incoming_messages(recv_sock, recv_buffer, drv):
    """Handle incoming OSC messages"""
    try:
        bytes_received, addr = recv_sock.recvfrom_into(recv_buffer)
        if bytes_received > 0:
            data = recv_buffer[:bytes_received]
            osc_address = parse_osc_message(data)
            if osc_address:
                handle_incoming_osc(osc_address, drv)
    except OSError:
        # No data received (timeout), continue
        pass
    except Exception as e:
        print(f"Error receiving OSC: {e}")

# ============================================================================
# MAIN APPLICATION
# ============================================================================

def main():
    """Main application entry point"""
    # Load configuration
    config = load_configuration()
    
    # Initialize hardware
    btn = setup_button()
    drv = setup_haptic()
    
    # Connect to WiFi
    esp32_ip = connect_wifi(config)
    if esp32_ip is None:
        print("Failed to connect to WiFi. Check credentials and try again.")
        return
    
    # Setup network sockets
    send_sock, recv_sock = setup_sockets(config)
    recv_buffer = bytearray(1024)
    
    # Send handshake message to announce device startup
    print("Sending startup handshake...")
    send_handshake(send_sock, config)
    
    print("Ready! Press button...")
    prev_btn_state = True  # Assume button is not pressed at start (HIGH)
    
    # Main loop
    while True:
        # Handle incoming OSC messages
        handle_incoming_messages(recv_sock, recv_buffer, drv)
        
        # Handle button events
        prev_btn_state = handle_button_events(btn, prev_btn_state, send_sock, config, drv)
        
        time.sleep(0.05)

# Start the application
if __name__ == "__main__":
    main()