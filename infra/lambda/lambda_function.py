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
import re
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

# ── Validation rules ────────────────────────────────────────────────
# event_type must be one of the form's <option> values (index.html).
EVENT_TYPES = {
    "wedding", "corporate", "birthday", "quinceanera",
    "anniversary", "nightclub", "other",
}

# Max accepted length per field. Rejects oversized payloads and keeps every
# stored item far under DynamoDB's 400 KB item limit.
MAX_LEN = {
    "name": 100, "email": 254, "phone": 40, "event_date": 10,
    "event_type": 20, "venue": 200, "message": 2000,
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATE_RE  = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Honeypot — a hidden form field real visitors never fill. If it arrives
# non-empty the request is almost certainly a bot: we return success (so the
# bot sees no signal) but store and email nothing.
HONEYPOT_FIELD = "website"


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

    if not isinstance(data, dict):
        return _response(400, {"error": "Cuerpo de la solicitud no válido"})

    # Honeypot — silently drop bot submissions (pretend success, store nothing).
    if str(data.get(HONEYPOT_FIELD, "")).strip():
        return _response(200, {"ok": True})

    # 2. VALIDATE — never trust the browser; re-check what the JS checks.
    #    Coerce to str first so non-string JSON values can't crash .strip().
    name       = str(data.get("name", "")).strip()
    email      = str(data.get("email", "")).strip()
    phone      = str(data.get("phone", "")).strip()
    event_date = str(data.get("event_date", "")).strip()
    event_type = str(data.get("event_type", "")).strip()
    venue      = str(data.get("venue", "")).strip()
    message    = str(data.get("message", "")).strip()

    if (not name
            or not EMAIL_RE.match(email)
            or not DATE_RE.match(event_date)
            or event_type not in EVENT_TYPES):
        return _response(400, {"error": "Faltan campos requeridos o son inválidos"})

    values = {"name": name, "email": email, "phone": phone,
              "event_date": event_date, "event_type": event_type,
              "venue": venue, "message": message}
    if any(len(v) > MAX_LEN[k] for k, v in values.items()):
        return _response(400, {"error": "Uno o más campos exceden la longitud permitida"})

    booking = {
        "id":        str(uuid.uuid4()),                       # partition key
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "name":      name,
        "email":     email,
        "phone":     phone,
        "eventDate": event_date,
        "eventType": event_type,
        "venue":     venue,
        "message":   message,
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
                    f"Teléfono: {booking['phone']}\n"
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
