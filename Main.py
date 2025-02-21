import os
import time
import json
import threading
import random
import smbus2
import RPi.GPIO as GPIO
from flask import Flask, render_template, request, jsonify
from mfrc522 import SimpleMFRC522
from gpiozero import Button, Servo

# LCD I2C Setup
I2C_ADDR = 0x27  # Change if necessary
BACKLIGHT = 0x08
ENABLE = 0b00000100
LCD_CLEARDISPLAY = 0x01
LCD_RETURNHOME = 0x02
LCD_ENTRYMODESET = 0x04
LCD_DISPLAYCONTROL = 0x08
LCD_FUNCTIONSET = 0x20
LCD_4BITMODE = 0x00
LCD_2LINE = 0x08
LCD_5x8DOTS = 0x00
LCD_DISPLAYON = 0x04
bus = smbus2.SMBus(1)

def lcd_write(data, mode=0):
    high_nibble = mode | (data & 0xF0) | BACKLIGHT
    low_nibble = mode | ((data << 4) & 0xF0) | BACKLIGHT
    bus.write_byte(I2C_ADDR, high_nibble | ENABLE)
    bus.write_byte(I2C_ADDR, high_nibble)
    bus.write_byte(I2C_ADDR, low_nibble | ENABLE)
    bus.write_byte(I2C_ADDR, low_nibble)
    time.sleep(0.002)

def lcd_command(cmd):
    lcd_write(cmd, 0)

def lcd_char(char):
    lcd_write(ord(char), 1)
    time.sleep(0.002)

def lcd_string(message, line):
    line_address = [0x80, 0xC0]
    lcd_command(line_address[line])
    for char in message.ljust(16):
        lcd_char(char.encode('ascii', 'ignore').decode())

def lcd_init():
    lcd_command(LCD_FUNCTIONSET | LCD_4BITMODE | LCD_2LINE | LCD_5x8DOTS)
    lcd_command(LCD_DISPLAYCONTROL | LCD_DISPLAYON)
    lcd_command(LCD_ENTRYMODESET | 0x02)
    lcd_command(LCD_CLEARDISPLAY)
    lcd_command(LCD_RETURNHOME)
    time.sleep(0.2)

def clear_lcd():
    lcd_command(LCD_CLEARDISPLAY)
    lcd_command(LCD_RETURNHOME)
    time.sleep(0.2)

def update_lcd(message):
    clear_lcd()
    if len(message) > 16:
        lcd_string(message[:16], 0)
        lcd_string(message[16:32], 1)
    else:
        lcd_string(message, 0)

# RFID & Hardware Setup
reader = SimpleMFRC522()
servo = Servo(18)
button_add = Button(23)
button_remove = Button(24)

def move_servo(angle):
    servo.value = angle / 90.0
    time.sleep(1)

def add_rfid():
    while True:
        button_add.wait_for_press()
        update_lcd("Scan Card to Add")
        uid, _ = reader.read()
        uid = str(uid)
        if uid not in registered_uids:
            registered_uids[uid] = True
            with open("rfid_data.json", "w") as file:
                json.dump(registered_uids, file)
            update_lcd(f"Added: {uid}")
        else:
            update_lcd("Card Exists")
        time.sleep(2)

def remove_rfid():
    while True:
        button_remove.wait_for_press()
        update_lcd("Scan Card to Remove")
        uid, _ = reader.read()
        uid = str(uid)
        if uid in registered_uids:
            del registered_uids[uid]
            reserved_uids.discard(uid)
            with open("rfid_data.json", "w") as file:
                json.dump(registered_uids, file)
            update_lcd(f"Removed: {uid}")
        else:
            update_lcd("Card Not Found")
        time.sleep(2)

def detect_entry():
    while True:
        update_lcd("Scan Card to Enter")
        uid, _ = reader.read()
        uid = str(uid)
        if uid in registered_uids:
            if None in slots:
                slots[slots.index(None)] = uid
                move_servo(90)
                time.sleep(3)
                move_servo(0)
                update_lcd("Entry Granted")
            else:
                update_lcd("Parking Full!")
        else:
            update_lcd("Access Denied")
        time.sleep(1)

def detect_exit():
    while True:
        update_lcd("Scan Card to Exit")
        uid, _ = reader.read()
        uid = str(uid)
        if uid in slots:
            slots[slots.index(uid)] = None
            reserved_uids.discard(uid)
            with open("reserved_data.json", "w") as file:
                json.dump(list(reserved_uids), file)
            move_servo(90)
            time.sleep(3)
            move_servo(0)
            update_lcd("Exit Granted")
        else:
            update_lcd("Unauthorized Exit!")
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
    lcd_init()
    threading.Thread(target=add_rfid, daemon=True).start()
    threading.Thread(target=remove_rfid, daemon=True).start()
    threading.Thread(target=detect_entry, daemon=True).start()
    threading.Thread(target=detect_exit, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=True)
