import RPi.GPIO as GPIO
import time
import json
import threading
from flask import Flask, render_template, request, jsonify
from mfrc522 import SimpleMFRC522
import smbus
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

# LCD I2C Setup
I2C_ADDR = 0x27  # Change if necessary
bus = smbus.SMBus(1)

# RFID Setup
reader = SimpleMFRC522()

# Push Buttons for Adding/Removing RFID
BTN_ADD = 5
BTN_REMOVE = 6
GPIO.setup(BTN_ADD, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(BTN_REMOVE, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Parking Slots (Initially all available)
PARKING_SLOTS = 4
available_slots = PARKING_SLOTS
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


def update_lcd(message):
    """ Display messages on LCD """
    print(f"LCD: {message}")  # Replace with actual LCD I2C commands


def add_rfid():
    """ Add RFID card when button is pressed """
    while True:
        if GPIO.input(BTN_ADD) == GPIO.LOW:
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
    """ Remove RFID card when button is pressed """
    while True:
        if GPIO.input(BTN_REMOVE) == GPIO.LOW:
            print("Place RFID card to remove...")
            update_lcd("Scan Card to Remove")
            uid, _ = reader.read()
            uid = str(uid)

            if uid in registered_uids:
                del registered_uids[uid]
                with open("rfid_data.json", "w") as file:
                    json.dump(registered_uids, file)
                print(f"RFID {uid} removed!")
                update_lcd(f"Removed: {uid}")
            else:
                update_lcd("Card Not Found")
            time.sleep(2)


def detect_entry():
    """ Detect vehicle entry and authenticate via RFID """
    global available_slots
    while True:
        if GPIO.input(IR_ENTRY) == 0:
            print("Vehicle detected at entry...")
            update_lcd("Scanning RFID")
            uid, _ = reader.read()
            uid = str(uid)

            if uid in registered_uids:
                if available_slots > 0:
                    available_slots -= 1
                    move_servo(90)
                    time.sleep(3)
                    move_servo(0)
                    update_lcd("Entry Granted")
                    print(f"Entry granted: {uid}")
                else:
                    update_lcd("Parking Full!")
            else:
                update_lcd("Access Denied")
                print("Access Denied!")
            time.sleep(1)


def detect_exit():
    """ Detect vehicle exit and free slot """
    global available_slots
    while True:
        if GPIO.input(IR_EXIT) == 0:
            print("Vehicle detected at exit...")
            if available_slots < PARKING_SLOTS:
                available_slots += 1
                move_servo(90)
                time.sleep(3)
                move_servo(0)
                update_lcd("Exit Granted")
                print("Vehicle exited.")
            time.sleep(1)


# Flask Web App
app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/status", methods=["GET"])
def status():
    """ Return the number of available slots """
    return jsonify({"available_slots": available_slots})

@app.route("/reserve", methods=["POST"])
def reserve():
    """ Reserve slot only if UID is registered """
    global available_slots
    data = request.get_json()
    uid = data.get("uid")

    if uid not in registered_uids:
        return jsonify({"message": "Access Denied: Invalid UID"}), 403

    if available_slots > 0:
        available_slots -= 1
        return jsonify({"message": "Slot Reserved"})
    else:
        return jsonify({"message": "Parking Full"}), 400


if __name__ == "__main__":
    threading.Thread(target=add_rfid, daemon=True).start()
    threading.Thread(target=remove_rfid, daemon=True).start()
    threading.Thread(target=detect_entry, daemon=True).start()
    threading.Thread(target=detect_exit, daemon=True).start()

    app.run(host="0.0.0.0", port=5000, debug=True)