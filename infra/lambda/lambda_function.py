"""
DJ Johnny — booking form handler
djjohnnydenver.com

Receives a booking submission from the static site (API Gateway → Lambda),
stores it in DynamoDB, and emails the details to DJ Johnny via SES.

Runtime: Python 3.13 (boto3 is preinstalled in the Lambda runtime)

Environment variables (set on the Lambda function):
  TABLE_NAME    DynamoDB table name        (default: chupon-bookings)
  FROM_ADDRESS  SES-verified sender        (default: bookings@djjohnnydenver.com)
  TO_ADDRESS    inbox that receives leads  (default: djjohnny74@yahoo.com)
  ALLOW_ORIGIN  CORS origin to allow       (default: https://djjohnnydenver.com)
"""

import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

TABLE_NAME   = os.environ.get("TABLE_NAME", "chupon-bookings")
FROM_ADDRESS = os.environ.get("FROM_ADDRESS", "bookings@djjohnnydenver.com")
TO_ADDRESS   = os.environ.get("TO_ADDRESS", "djjohnny74@yahoo.com")
ALLOW_ORIGIN = os.environ.get("ALLOW_ORIGIN", "https://djjohnnydenver.com")

ddb = boto3.resource("dynamodb").Table(TABLE_NAME)
ses = boto3.client("sesv2")

CORS = {
    "Access-Control-Allow-Origin": ALLOW_ORIGIN,   # locked to your domain
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


def _response(status, payload):
    return {"statusCode": status, "headers": CORS, "body": json.dumps(payload)}


def handler(event, context):
    # Answer the CORS preflight if it reaches the function
    method = (event.get("requestContext", {})
                   .get("http", {})
                   .get("method", "POST"))
    if method == "OPTIONS":
        return _response(200, {"ok": True})

    # 1. PARSE — API Gateway hands the form JSON in as a string
    try:
        data = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        return _response(400, {"error": "Cuerpo de la solicitud no válido"})

    # 2. VALIDATE — never trust the browser; re-check what the JS checks
    if (not data.get("name", "").strip()
            or "@" not in data.get("email", "")
            or not data.get("event_date")
            or not data.get("event_type")):
        return _response(400, {"error": "Faltan campos requeridos"})

    booking = {
        "id":        str(uuid.uuid4()),                       # partition key
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "name":      data["name"].strip(),
        "email":     data["email"].strip(),
        "phone":     data.get("phone", "").strip(),
        "eventDate": data["event_date"],
        "eventType": data["event_type"],
        "venue":     data.get("venue", "").strip(),
        "message":   data.get("message", "").strip(),
    }

    try:
        # 3. STORE — durable record of every booking
        ddb.put_item(Item=booking)

        # 4. NOTIFY — email DJ Johnny. From = verified domain (passes DMARC);
        #    To = his Yahoo inbox; Reply-To = the customer so he can just reply.
        ses.send_email(
            FromEmailAddress=FROM_ADDRESS,
            Destination={"ToAddresses": [TO_ADDRESS]},
            ReplyToAddresses=[booking["email"]],
            Content={"Simple": {
                "Subject": {"Data": f"Nueva reserva: {booking['eventType']} — {booking['eventDate']}"},
                "Body": {"Text": {"Data": (
                    f"Nombre:  {booking['name']}\n"
                    f"Email:   {booking['email']}\n"
                    f"Teléfono:{booking['phone']}\n"
                    f"Evento:  {booking['eventType']} el {booking['eventDate']}\n"
                    f"Lugar:   {booking['venue']}\n\n"
                    f"Mensaje:\n{booking['message']}\n\n"
                    f"— Recibido {booking['createdAt']} (id {booking['id']})"
                )}},
            }},
        )

        # 5. RESPOND — this JSON is what fetch() in main.js receives
        return _response(200, {"ok": True})

    except ClientError as err:
        print(err)  # lands in CloudWatch Logs automatically
        return _response(500, {"error": "Error al guardar la reserva"})
