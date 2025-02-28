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

@app.route('/logout_imessage', methods=['POST'])
def logout_imessage():
    try:
        logout_script = '''
        tell application "Messages"
            activate
        end tell
        
        tell application "System Events"
            tell process "Messages"
                -- Open Preferences
                keystroke "," using command down
                delay 0.3
                
                -- Click on iMessage tab
                click button "iMessage" of toolbar 1 of window 1
                delay 0.3
                
                -- Try to find the Sign Out button by its UI element description
                set foundButton to false
                
                -- Get all UI elements in the window
                set allElements to entire contents of window 1
                
                -- Loop through all elements looking for the Sign Out button
                repeat with anElement in allElements
                    try
                        if name of anElement is "Sign Out" then
                            click anElement
                            set foundButton to true
                            delay 0.3
                            exit repeat
                        end if
                    end try
                end repeat
                
                -- If we couldn't find it by name, try by class and position
                if not foundButton then
                    -- Get all buttons
                    set allButtons to buttons of window 1
                    
                    -- Look for buttons in the top right area
                    repeat with aButton in allButtons
                        try
                            set btnPos to position of aButton
                            
                            -- Check if this looks like our Sign Out button (in top right)
                            if (item 1 of btnPos) > 700 and (item 2 of btnPos) < 350 then
                                click aButton
                                set foundButton to true
                                delay 0.3
                                exit repeat
                            end if
                        end try
                    end repeat
                end if
                
                -- If still not found, try a direct click at the position from the screenshot
                if not foundButton then
                    -- Based on your screenshot, try clicking at this position
                    click at {813, 305}
                    delay 0.3
                end if
                
                -- Try to confirm Sign Out if dialog appears
                try
                    click button "Sign Out" of sheet 1 of window 1
                    delay 0.2
                end try
                
                -- Close preferences window
                keystroke "w" using command down
            end tell
        end tell
        
        return "Logout successful"
        '''
        
        result = subprocess.run(['osascript', '-e', logout_script], capture_output=True, text=True)
        
        if result.returncode == 0:
            return jsonify({
                'success': True, 
                'message': 'Successfully logged out of iMessage'
            })
        else:
            return jsonify({
                'success': False, 
                'error': result.stderr
            }), 500
            
    except Exception as e:
        print(f"Error logging out of iMessage: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/login_imessage', methods=['POST'])
def login_imessage():
    try:
        data = request.json
        if not data or 'apple_id' not in data or 'password' not in data:
            return jsonify({'success': False, 'error': 'Apple ID and password are required'}), 400
            
        apple_id = data['apple_id']
        password = data['password']
        
        login_script = f'''
        tell application "Messages"
            activate
        end tell
        
        delay 0.5
        
        tell application "System Events"
            tell process "Messages"
                -- First screen: Enter Apple ID
                try
                    -- Clear any existing text in the first field (Apple ID)
                    set value of text field 1 of window 1 to ""
                    delay 0.1
                    set value of text field 1 of window 1 to "{apple_id}"
                    delay 0.1
                on error
                    -- If setting value directly fails, try keystroke
                    keystroke "a" using {{command down}}
                    keystroke "{apple_id}"
                    delay 0.1
                end try
                
                -- Click Next/Continue button or press return
                try
                    click button "Sign In" of window 1
                on error
                    try
                        click button "Next" of window 1
                    on error
                        try
                            click button "Continue" of window 1
                        on error
                            keystroke return
                        end try
                    end try
                end try
                
                -- Wait for second screen
                delay 1
                
                -- Second screen: Enter Apple ID again and password
                -- First make sure we're in the first field (Apple ID)
                click text field 1 of window 1
                delay 0.1
                
                -- Clear and enter Apple ID again
                keystroke "a" using {{command down}}
                keystroke (ASCII character 8) -- backspace
                delay 0.1
                keystroke "{apple_id}"
                delay 0.1
                
                -- Explicitly click the password field
                try
                    click text field 2 of window 1
                on error
                    -- If clicking fails, try tabbing
                    keystroke tab
                end try
                
                delay 0.1
                
                -- Clear any existing text in password field
                keystroke "a" using {{command down}}
                keystroke (ASCII character 8) -- backspace
                delay 0.1
                
                -- Type password character by character
                set pwd to "{password}"
                repeat with i from 1 to length of pwd
                    set c to character i of pwd
                    keystroke c
                    delay 0.05 -- Small delay between characters
                end repeat
                
                delay 0.1
                
                -- Click Sign In button in bottom right
                try
                    click button "Sign In" of window 1
                on error
                    -- If button click fails, try tab + return to reach the button
                    keystroke tab
                    keystroke tab
                    keystroke return
                end try
                
                return "Login initiated"
            end tell
        end tell
        '''
        
        result = subprocess.run(['osascript', '-e', login_script], capture_output=True, text=True)
        
        if result.returncode == 0:
            return jsonify({
                'success': True, 
                'message': 'Login initiated, now call /click_other_options'
            })
        else:
            return jsonify({'success': False, 'error': result.stderr}), 500
            
    except Exception as e:
        print(f"Error logging into iMessage: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/click_other_options_tab', methods=['POST'])
def click_other_options_tab():
    try:
        # This script uses tab navigation to reach the "Other options" button
        
        tab_script = '''
        tell application "Messages"
            activate
        end tell
        
        -- Wait for Messages to come to the foreground
        delay 1
        
        -- Take a screenshot before we start
        do shell script "screencapture -x /tmp/before_tab.png"
        
        tell application "System Events"
            tell process "Messages"
                -- Get the window position and size for screenshots
                set winPosition to position of window 1
                set winSize to size of window 1
                set winLeft to item 1 of winPosition
                set winTop to item 2 of winPosition
                set winWidth to item 1 of winSize
                set winHeight to item 2 of winSize
                
                -- Press tab twice to navigate to the "Other options" button
                -- First tab should go to "Learn more..."
                -- Second tab should go to "Other options"
                keystroke tab
                delay 0.5
                keystroke tab
                delay 0.5
                
                -- Take a screenshot after tabbing
                do shell script "screencapture -x -R" & winLeft & "," & winTop & "," & winWidth & "," & winHeight & " /tmp/after_tab.png"
                
                -- Press return/enter to click the button
                keystroke return
                
                -- Wait for any UI changes
                delay 1
                
                -- Take a screenshot after clicking
                do shell script "screencapture -x -R" & winLeft & "," & winTop & "," & winWidth & "," & winHeight & " /tmp/after_click_tab.png"
                
                -- Check if we now have a verification code field
                set success to false
                try
                    if exists text field 1 of window 1 then
                        set fieldValue to value of attribute "AXPlaceholderValue" of text field 1 of window 1
                        if fieldValue contains "code" or fieldValue contains "verification" then
                            set success to true
                        end if
                    end if
                on error
                    -- Not a verification code screen
                end try
                
                -- Press Escape to dismiss any remaining dialogs
                delay 2
                key code 53
                delay 0.5

                return success
            end tell
        end tell
        '''
        
        result = subprocess.run(['osascript', '-e', tab_script], 
                               capture_output=True, text=True)
        
        if result.returncode == 0:
            success = result.stdout.strip().lower() == "true"
            
            return jsonify({
                'success': True,
                'verification_screen_reached': success,
            })
        else:
            return jsonify({'success': False, 'error': result.stderr}), 500
            
    except Exception as e:
        print(f"Error with tab navigation: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    print("Registered routes:")
    for rule in app.url_map.iter_rules():
        print(rule)
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT_NUMBER', '3000')))