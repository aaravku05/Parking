import RPi.GPIO as GPIO
import time
import json
import threading
from flask import Flask, render_template, request, jsonify
from mfrc522 import SimpleMFRC522
import smbus2
import pigpio
import os

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

# I2C LCD Setup
I2C_ADDR = 0x27  # Change if necessary
bus = smbus2.SMBus(1)
LCD_BACKLIGHT = 0x08  # LCD backlight on
ENABLE = 0b00000100

def lcd_send_byte(bits, mode):
    high = mode | (bits & 0xF0) | LCD_BACKLIGHT
    low = mode | ((bits << 4) & 0xF0) | LCD_BACKLIGHT
    bus.write_byte(I2C_ADDR, high)
    lcd_toggle_enable(high)
    bus.write_byte(I2C_ADDR, low)
    lcd_toggle_enable(low)

def lcd_toggle_enable(bits):
    time.sleep(0.0005)
    bus.write_byte(I2C_ADDR, (bits | ENABLE))
    time.sleep(0.0005)
    bus.write_byte(I2C_ADDR, (bits & ~ENABLE))
    time.sleep(0.0005)

def lcd_init():
    lcd_send_byte(0x33, 0)
    lcd_send_byte(0x32, 0)
    lcd_send_byte(0x28, 0)
    lcd_send_byte(0x0C, 0)
    lcd_send_byte(0x06, 0)
    lcd_send_byte(0x01, 0)
    time.sleep(0.2)

def lcd_display_string(message, line):
    lines = [0x80, 0xC0]
    lcd_send_byte(lines[line], 0)
    for char in message.ljust(16):
        lcd_send_byte(ord(char), 1)

lcd_init()

# RFID Setup
reader = SimpleMFRC522()

# Push Buttons for Adding/Removing RFID
BTN_ADD = 5
BTN_REMOVE = 6
GPIO.setup(BTN_ADD, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(BTN_REMOVE, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Parking Slots (Initially empty)
PARKING_SLOTS = 4
slots_available = PARKING_SLOTS
registered_uids = {}

# Load registered UIDs from file
if os.path.exists("rfid_data.json"):
    with open("rfid_data.json", "r") as file:
        registered_uids = json.load(file)

def move_servo(angle):
    """ Move servo (0° for closed, 90° for open) """
    duty_cycle = (angle / 18.0) + 2.5
    pi.set_servo_pulsewidth(SERVO_PIN, duty_cycle * 1000)
    time.sleep(1)
    pi.set_servo_pulsewidth(SERVO_PIN, 0)

def update_lcd():
    """ Display available slots on LCD """
    lcd_display_string(f"Slots Available: {slots_available}", 0)
    lcd_display_string("", 1)

def add_rfid():
    """ Add RFID card when button is pressed """
    global registered_uids
    while True:
        if GPIO.input(BTN_ADD) == GPIO.LOW:
            lcd_display_string("Scan New Card", 0)
            uid, _ = reader.read()
            uid = str(uid)

            if uid not in registered_uids:
                registered_uids[uid] = True
                with open("rfid_data.json", "w") as file:
                    json.dump(registered_uids, file)
                lcd_display_string(f"Added: {uid}", 0)
            else:
                lcd_display_string("Card Exists", 0)
            time.sleep(2)
            update_lcd()

def remove_rfid():
    """ Remove RFID card when button is pressed """
    global registered_uids
    while True:
        if GPIO.input(BTN_REMOVE) == GPIO.LOW:
            lcd_display_string("Scan Card to Remove", 0)
            uid, _ = reader.read()
            uid = str(uid)

            if uid in registered_uids:
                del registered_uids[uid]
                with open("rfid_data.json", "w") as file:
                    json.dump(registered_uids, file)
                lcd_display_string(f"Removed: {uid}", 0)
            else:
                lcd_display_string("Card Not Found", 0)
            time.sleep(2)
            update_lcd()

def detect_entry():
    """ Detect vehicle entry and authenticate via RFID """
    global slots_available
    while True:
        if GPIO.input(IR_ENTRY) == 0 and slots_available > 0:
            lcd_display_string("Scan RFID Card", 0)
            uid, _ = reader.read()
            uid = str(uid)

            if uid in registered_uids:
                slots_available -= 1
                move_servo(90)
                time.sleep(3)
                move_servo(0)
                lcd_display_string("Entry Granted", 0)
            else:
                lcd_display_string("Access Denied", 0)
            time.sleep(2)
            update_lcd()

def detect_exit():
    """ Detect vehicle exit and free slot """
    global slots_available
    while True:
        if GPIO.input(IR_EXIT) == 0:
            slots_available += 1
            move_servo(90)
            time.sleep(3)
            move_servo(0)
            lcd_display_string("Exit Granted", 0)
            time.sleep(2)
            update_lcd()

# Flask Web App
app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/status", methods=["GET"])
def status():
    return jsonify({"available_slots": slots_available})

@app.route("/reserve", methods=["POST"])
def reserve():
    """ Reserve slot only if UID is registered """
    global slots_available
    data = request.get_json()
    uid = data.get("uid")

    if uid not in registered_uids:
        return jsonify({"message": "Access Denied: Invalid UID"}), 403

    if slots_available > 0:
        slots_available -= 1
        return jsonify({"message": "Slot Reserved"})
    else:
        return jsonify({"message": "Parking Full"}), 400

if __name__ == "__main__":
    threading.Thread(target=add_rfid, daemon=True).start()
    threading.Thread(target=remove_rfid, daemon=True).start()
    threading.Thread(target=detect_entry, daemon=True).start()
    threading.Thread(target=detect_exit, daemon=True).start()

    update_lcd()
    app.run(host="0.0.0.0", port=5000, debug=True)