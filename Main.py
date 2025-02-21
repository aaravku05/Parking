import RPi.GPIO as GPIO
import time
import json
import threading
from flask import Flask, render_template, request, jsonify
from mfrc522 import SimpleMFRC522
import pigpio
import os
from RPLCD.i2c import CharLCD

# GPIO setup
GPIO.setmode(GPIO.BCM)

# IR Sensors (Active LOW)
IR_ENTRY = 17
IR_EXIT = 27
GPIO.setup(IR_ENTRY, GPIO.IN)
GPIO.setup(IR_EXIT, GPIO.IN)

# Servo Motor Setup (Using pigpio)
SERVO_PIN = 22
pi = pigpio.pi()
pi.set_mode(SERVO_PIN, pigpio.OUTPUT)

# LCD I2C Setup
lcd = CharLCD(i2c_expander="PCF8574", address=0x27, port=1,
              cols=16, rows=2, charmap="A02", auto_linebreaks=True)
lcd.backlight_enabled = True  # Enable LCD backlight

def update_lcd(message):
    """Display messages on LCD."""
    lcd.clear()
    lcd.write_string(message[:16])  # Limit to 16 characters

# RFID Setup
reader = SimpleMFRC522()

# Push Buttons for Adding/Removing RFID
BTN_ADD = 5
BTN_REMOVE = 6
GPIO.setup(BTN_ADD, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(BTN_REMOVE, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Parking Slots & Registered UIDs
PARKING_SLOTS = 4
slots = [None] * PARKING_SLOTS  # List to store UID occupying slots
registered_uids = {}
reserved_uids = set()

# Load registered UIDs from file
if os.path.exists("rfid_data.json"):
    with open("rfid_data.json", "r") as file:
        registered_uids = json.load(file)

# Load reserved UIDs from file
if os.path.exists("reserved_data.json"):
    with open("reserved_data.json", "r") as file:
        reserved_uids = set(json.load(file))

def move_servo(angle):
    """Move servo (0° for closed, 90° for open)."""
    pulse_width = 500 + (angle / 90.0) * 2000  # Map 0° to 500us, 90° to 2500us
    pi.set_servo_pulsewidth(SERVO_PIN, pulse_width)
    time.sleep(1)
    pi.set_servo_pulsewidth(SERVO_PIN, 0)

def add_rfid():
    """Add RFID card when button is pressed."""
    while True:
        GPIO.wait_for_edge(BTN_ADD, GPIO.FALLING)
        time.sleep(0.2)  # Debounce
        print("Place RFID card to register...")
        update_lcd("Scan New Card")
        uid, _ = reader.read()
        uid = str(uid)

        if uid not in registered_uids:
            registered_uids[uid] = True
            with open("rfid_data.json", "w") as file:
                json.dump(registered_uids, file)
            print(f"RFID {uid} added!")
            update_lcd(f"Added: {uid}")
        else:
            update_lcd("Card Already Exists")
        time.sleep(2)

def remove_rfid():
    """Remove RFID card when button is pressed."""
    while True:
        GPIO.wait_for_edge(BTN_REMOVE, GPIO.FALLING)
        time.sleep(0.2)  # Debounce
        print("Place RFID card to remove...")
        update_lcd("Scan Card to Remove")
        uid, _ = reader.read()
        uid = str(uid)

        if uid in registered_uids:
            del registered_uids[uid]
            reserved_uids.discard(uid)
            with open("rfid_data.json", "w") as file:
                json.dump(registered_uids, file)
            with open("reserved_data.json", "w") as file:
                json.dump(list(reserved_uids), file)
            print(f"RFID {uid} removed!")
            update_lcd(f"Removed: {uid}")
        else:
            update_lcd("Card Not Found")
        time.sleep(2)

def detect_entry():
    """Detect vehicle entry and authenticate via RFID."""
    global slots
    while True:
        if GPIO.input(IR_ENTRY) == 0:
            print("Vehicle detected at entry...")
            update_lcd("Scanning RFID")
            uid, _ = reader.read()
            uid = str(uid)

            if uid in registered_uids:
                if None in slots:
                    slots[slots.index(None)] = uid
                    move_servo(90)
                    time.sleep(3)
                    move_servo(0)
                    update_lcd("Entry Granted")
                    print(f"Entry granted: {uid}")
                else:
                    update_lcd("Parking Full!")
                    print("Parking Full!")
            else:
                update_lcd("Access Denied")
                print("Access Denied!")
            time.sleep(1)

def detect_exit():
    """Detect vehicle exit with RFID verification."""
    global slots, reserved_uids

    while True:
        if GPIO.input(IR_EXIT) == 0:
            print("Vehicle detected at exit...")
            update_lcd("Scan RFID to Exit")
            uid, _ = reader.read()
            uid = str(uid)

            if uid in slots:
                slot_index = slots.index(uid)
                slots[slot_index] = None  # Free the slot
                
                if uid in reserved_uids:
                    reserved_uids.remove(uid)
                    with open("reserved_data.json", "w") as file:
                        json.dump(list(reserved_uids), file)

                move_servo(90)
                time.sleep(3)
                move_servo(0)
                update_lcd("Exit Granted")
                print(f"Vehicle with UID {uid} exited.")
            else:
                update_lcd("Unauthorized Exit!")
                print(f"Unauthorized exit attempt by UID {uid}")
            
            time.sleep(1)

# Flask Web App
app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/status", methods=["GET"])
def status():
    available_slots = sum(1 for slot in slots if slot is None)
    return jsonify({"available_slots": available_slots})

@app.route("/reserve", methods=["POST"])
def reserve():
    """Reserve a slot if available and UID is registered."""
    global slots
    data = request.get_json()
    uid = data.get("uid")

    if uid not in registered_uids:
        return jsonify({"message": "Access Denied: Invalid UID"}), 403

    if uid in reserved_uids:
        return jsonify({"message": "UID already reserved"})

    if None in slots:
        slots[slots.index(None)] = uid
        reserved_uids.add(uid)
        with open("reserved_data.json", "w") as file:
            json.dump(list(reserved_uids), file)
        return jsonify({"message": "Reservation Successful"})
    else:
        return jsonify({"message": "Parking Full"}), 400

if __name__ == "__main__":
    threading.Thread(target=add_rfid, daemon=True).start()
    threading.Thread(target=remove_rfid, daemon=True).start()
    threading.Thread(target=detect_entry, daemon=True).start()
    threading.Thread(target=detect_exit, daemon=True).start()

    app.run(host="0.0.0.0", port=5000, debug=True)
