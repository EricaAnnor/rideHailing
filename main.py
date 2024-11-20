import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import random
import time
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# Database connection setup
try:
    conn = psycopg2.connect(
        database="ride_hailing",
        user="postgres",
        password="password",
        host="localhost",
        port="5432",
        cursor_factory=RealDictCursor
    )
    print("Connected to the database")
except Exception as e:
    print(f"Error connecting to the database: {e}")
    conn = None

scheduler = BackgroundScheduler()
scheduler.start()

# Generate unique ID
def generate_unique_id():
    unique_id = int(f"{int(time.time() * 1000)}{random.randint(0, 999)}")
    return unique_id

# Periodic ride update function
def send_ride_updates():
    if not conn:
        return

    try:
        cur = conn.cursor()
        cur.execute(
            'SELECT * FROM "rides" WHERE "status" IN (%s, %s)',
            ("driver_matched", "on_ride")
        )
        rides = cur.fetchall()

        for ride in rides:
            phone_number = ride["user_id"]  
            driver_name = ride["driver_name"]
            eta = max(ride["estimated_arrival_time"] - 1, 0) 
            ride_id = ride["id"]

            if eta == 0:
                # Update ride status to on_ride
                cur.execute(
                    'UPDATE "rides" SET "status" = %s WHERE "id" = %s',
                    ("on_ride", ride_id)
                )
                message = f"Your driver {driver_name} has arrived. Your ride is starting now!"
            else:
                # Update ETA
                cur.execute(
                    'UPDATE "rides" SET "estimated_arrival_time" = %s WHERE "id" = %s',
                    (eta, ride_id)
                )
                message = f"Your driver {driver_name} is on the way! ETA: {eta} minutes."

            # Replace the next line with a function to send the message to the passenger
            print(f"Sending update to {phone_number}: {message}")
            conn.commit()

    except Exception as e:
        print(f"Error in sending ride updates: {e}")
    finally:
        cur.close()

# Schedule periodic ride updates every 1 minute
scheduler.add_job(send_ride_updates, "interval", minutes=1)

@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    incoming_msg = request.values.get("Body", "").strip().lower()
    phone_number = request.values.get("From").replace("whatsapp:", "")
    latitude = request.values.get("Latitude")
    longitude = request.values.get("Longitude")
    response = MessagingResponse()

    if not conn:
        response.message("Database connection error. Please try again later.")
        return str(response)

    try:
        cur = conn.cursor()

        # Fetch user details
        cur.execute('SELECT * FROM "userprofile" WHERE "phonenumber" = %s', (phone_number,))
        user = cur.fetchone()

        if not user:
            # Start registration
            response.message("Welcome! Please provide your full name to start registration.")
            user_id = generate_unique_id()
            cur.execute(
                'INSERT INTO "userprofile" ("id", "phonenumber", "registered") VALUES (%s, %s, %s)',
                (user_id, phone_number, False)
            )
            conn.commit()

        elif incoming_msg == "history":
            # Fetch ride history
            cur.execute(
                'SELECT * FROM "rides" WHERE "user_id" = %s ORDER BY "ride_start" DESC LIMIT 5',
                (user["id"],)
            )
            rides = cur.fetchall()

            if not rides:
                response.message("You have no ride history.")
            else:
                history_message = "Your recent rides:\n"
                for ride in rides:
                    history_message += (
                        f"- Ride on {ride['ride_start']} to {ride['destination']} (Status: {ride['status']})\n"
                    )
                response.message(history_message)

        elif latitude and longitude:
            # Handle location sharing
            cur.execute(
                'SELECT * FROM "rides" WHERE "user_id" = %s ORDER BY "id" DESC LIMIT 1',
                (user["id"],)
            )
            ride = cur.fetchone()

            if ride and ride["status"] == "awaiting_location":
                # Save current location
                cur.execute(
                    'UPDATE "rides" SET "current_location" = %s, "current_location_coords" = point(%s, %s), "status" = %s WHERE "id" = %s',
                    (f"Lat: {latitude}, Lon: {longitude}", latitude, longitude, "awaiting_destination", ride["id"])
                )
                response.message("Thanks for sharing your current location. Now, please share your destination.")
                conn.commit()

            elif ride and ride["status"] == "awaiting_destination":
                # Save destination
                cur.execute(
                    'UPDATE "rides" SET "destination" = %s, "destination_coords" = point(%s, %s), "status" = %s WHERE "id" = %s',
                    (f"Lat: {latitude}, Lon: {longitude}", latitude, longitude, "driver_matched", ride["id"])
                )
                driver_name = random.choice(["Kwame Mensah", "Ama Ofori", "John Doe"])
                car_details = random.choice(["Toyota Corolla - GR1234X", "Hyundai Elantra - GT5678Z"])
                estimated_arrival_time = random.randint(5, 15)
                fare_estimate = round(random.uniform(10.00, 50.00), 2)

                cur.execute(
                    'UPDATE "rides" SET "driver_name" = %s, "car_details" = %s, "estimated_arrival_time" = %s, "fare_estimate" = %s WHERE "id" = %s',
                    (driver_name, car_details, estimated_arrival_time, fare_estimate, ride["id"])
                )
                response.message(
                    f"Driver matched! 🚗\nDriver: {driver_name}\nCar: {car_details}\nETA: {estimated_arrival_time} minutes\nFare Estimate: GHS {fare_estimate:.2f}"
                )
                conn.commit()

        elif incoming_msg == "ride":
            # Start ride booking
            response.message("Please share your current location using the location button.")
            cur.execute(
                'INSERT INTO "rides" ("user_id", "status") VALUES (%s, %s) RETURNING id',
                (user["id"], "awaiting_location")
            )
            conn.commit()

        else:
            response.message("To book a ride, type 'ride' and follow the instructions.")

    except Exception as e:
        response.message(f"An error occurred: {e}")
        print(f"Error: {e}")
    finally:
        cur.close()

    return str(response)


if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
