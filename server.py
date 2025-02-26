import time
import json
import threading
import os
from datetime import datetime
from flask import Flask, request, jsonify
from imessage_reader import fetch_data
import subprocess
from functools import wraps
from dotenv import load_dotenv
import traceback
from PIL import Image, ImageDraw

load_dotenv()

app = Flask(__name__)
PASSWORD = os.environ.get('PASSWORD')
MY_NAME = os.environ.get('YOUR_NAME')

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.headers.get('Api-Key') != PASSWORD:
            return jsonify({'error': 'Invalid API key'}), 401
        return f(*args, **kwargs)
    return decorated_function

global messages

DB_FILEPATH = os.environ.get('DB_FILEPATH')

def update_fd():
    global messages
    while True:
        messages = sorted(fetch_data.FetchData(DB_FILEPATH).get_messages(), key=sort_key, reverse=True)
        time.sleep(5)

threading.Thread(target=update_fd).start()

def sort_key(item):
    return datetime.strptime(item[2], '%Y-%m-%d %H:%M:%S')

def send(phone_number, message):
    message = message.replace('"', '\\"')
    applescript = f'''
    tell application "Messages"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy "{phone_number}" of targetService
        send "{message}" to targetBuddy
    end tell
    '''
    try:
        subprocess.run(['osascript', '-e', applescript])
    except Exception as e:
        print(f"Error sending message to {phone_number}: {e}")

@app.route('/')
def root():
    print(request)
    return jsonify({'messages': "root"}), 200

    
def check_imessage(phone_number):
    # Clean and format the phone number
    raw_number = phone_number.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    if raw_number.startswith("1"):
        raw_number = raw_number[1:]
    
    setup_script = '''
    tell application "Messages"
        activate
        delay 0.1
    end tell
    
    tell application "System Events"
        tell process "Messages"
            -- Create new message window
            keystroke "n" using {command down}
            delay 0.1
            
            -- Type the phone number
            keystroke "''' + phone_number + '''"
            delay 0.1
            
            -- Press Return/Enter
            keystroke return
            delay 0.1
            
            -- Get window position and size
            set msgWindow to window 1
            set winPos to position of msgWindow
            set winSize to size of msgWindow
            
            -- Get the title bar height (approximately 40 pixels)
            set titleBarHeight to 40
            
            -- Return coordinates for just the title bar area
            return {item 1 of winPos, item 2 of winPos, item 1 of winSize, titleBarHeight}
        end tell
    end tell
    '''
    
    try:
        print(f"\nChecking iMessage status for {phone_number}")
        
        # First make sure Messages app is running and window is set up
        print("Opening Messages app and setting up window...")
        setup_result = subprocess.run(['osascript', '-e', setup_script], capture_output=True, text=True)
        print(f"Setup script output: {setup_result.stdout.strip()}")
        
        # Parse window coordinates from the output
        if setup_result.stdout.strip():
            try:
                coords = [int(x) for x in setup_result.stdout.strip().split(", ")]
                x, y, width, height = coords
                print(f"Title bar coordinates: x={x}, y={y}, width={width}, height={height}")
                
                # Take a screenshot of just the title bar
                screenshot_path = "/tmp/messages_check.png"
                print(f"Taking screenshot of title bar...")
                
                region = f"{x},{y},{width},{height}"
                capture_result = subprocess.run(['screencapture', '-R', region, screenshot_path], capture_output=True, text=True)
                
                if os.path.exists(screenshot_path):
                    print(f"Screenshot created successfully")

                    IMESSAGE_BLUE = (0, 122, 255)
                    SMS_GREEN = (35, 151, 63)

                    def is_greenish(pixel):
                        r, g, b = pixel
                        return (60 <= r <= 90 and 
                                100 <= g <= 120 and 
                                60 <= b <= 90)
                    
                    def is_blueish(pixel):
                        r, g, b = pixel
                        return (30 <= r <= 60 and 
                                60 <= g <= 130 and 
                                90 <= b <= 250)
                    
                    with Image.open(screenshot_path) as img:
                        img = img.convert('RGB')
                        width, height = img.size
                        print(f"Title bar image dimensions: {width}x{height}")
                        
                        # Adjust scan area to focus more precisely on token
                        token_start_x = width // 3
                        token_width = width // 5  # Make this smaller to focus on just the token
                        token_area_y = height // 4  # Start 1/4 down from top
                        token_height = height // 2  # Scan middle half of height
                        
                        blue_count = 0
                        green_count = 0
                        
                        # Scan just the token area with more precise boundaries
                        print("\nScanning token area for colors...")
                        for x in range(token_start_x, token_start_x + token_width):
                            for y in range(token_area_y, token_area_y + token_height):
                                pixel = img.getpixel((x, y))
                                if is_blueish(pixel):
                                    blue_count += 1
                                elif is_greenish(pixel):
                                    green_count += 1
                        
                        print(f"\nPixel counts - Blue: {blue_count}, Green: {green_count}")
                        # Create debug image with overlay
                        debug_img = img.copy()
                        draw = ImageDraw.Draw(debug_img)
                        
                        # Draw scan area rectangle
                        draw.rectangle(
                            [
                                (token_start_x, token_area_y), 
                                (token_start_x + token_width, token_area_y + token_height)
                            ],
                            outline=(255, 0, 0),
                            width=2
                        )
                        
                        # Save debug image with overlay
                        debug_path = os.getcwd() + f"/messages_debug_{phone_number}.png"
                        debug_img.save(debug_path)
                        print(f"Debug screenshot saved to {debug_path}")
                        
                        # Clean up original
                        os.remove(screenshot_path)
                        
                        # Close Messages window
                        close_script = '''
                        tell application "System Events"
                            tell process "Messages"
                                keystroke "w" using {command down}
                            end tell
                        end tell
                        '''
                        subprocess.run(['osascript', '-e', close_script])
                        
                        # Determine if it's iMessage based on color counts
                        is_imessage = blue_count > green_count
                        print(f"Final determination: {'iMessage' if is_imessage else 'SMS'}")
                        return is_imessage
                        
                else:
                    print(f"Error: Screenshot was not created")
                    
            except Exception as e:
                print(f"Error processing screenshot: {e}")
                traceback.print_exc()
        
        return False
        
    except Exception as e:
        print(f"Error in lookup: {str(e)}")
        traceback.print_exc()
        return False

def is_color_similar(color1, color2, threshold=30):
    """Check if two colors are similar within a threshold."""
    r1, g1, b1 = color1
    r2, g2, b2 = color2
    
    # iMessage blue is approximately (0, 122, 255)
    # SMS green is approximately (35, 151, 63)
    
    return (abs(r1 - r2) <= threshold and 
            abs(g1 - g2) <= threshold and 
            abs(b1 - b2) <= threshold)

@app.route('/check_imessage/<phone_number>')
def check_imessage_route(phone_number):
    try:
        print(f"\n=== Starting iMessage check for {phone_number} ===")
        is_on_imessage = check_imessage(phone_number)
        response_data = {
            'phone_number': phone_number,
            'is_on_imessage': is_on_imessage,
            'debug_info': {
                'timestamp': datetime.now().isoformat(),
                'phone_format': 'valid' if phone_number.startswith('+') else 'invalid'
            }
        }
        print(f"Returning response: {json.dumps(response_data, indent=2)}")
        return jsonify(response_data)
    except Exception as e:
        print(f"Error in route handler: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("Registered routes:")
    for rule in app.url_map.iter_rules():
        print(rule)
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT_NUMBER', '3000')))