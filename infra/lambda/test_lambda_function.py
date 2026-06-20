"""
Unit tests for the booking Lambda handler.

No AWS access is required — the module-level DynamoDB and SES clients are
replaced with mocks in setUp, so nothing hits the network.

Run from this directory:
    python -m unittest test_lambda_function -v
or with pytest:
    pytest infra/lambda/test_lambda_function.py
"""

import json
import os
import sys
import types
import unittest
from unittest import mock

# Make `import lambda_function` work no matter the current working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Deterministic config, set BEFORE import (the module reads these at import time).
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ["TABLE_NAME"]   = "test-bookings"
os.environ["FROM_ADDRESS"] = "bookings@djjohnnydenver.com"
os.environ["TO_ADDRESS"]   = "djjohnny74@yahoo.com"
os.environ["ALLOW_ORIGIN"] = "https://djjohnnydenver.com"

# All AWS calls are mocked in setUp, so the real SDK isn't needed to unit test.
# If boto3/botocore aren't installed locally, register lightweight stubs so the
# handler still imports. (When the SDK is installed, the real modules are used.)
try:
    import boto3  # noqa: F401
except ModuleNotFoundError:
    boto3_stub = types.ModuleType("boto3")
    boto3_stub.resource = lambda *a, **k: mock.MagicMock()
    boto3_stub.client   = lambda *a, **k: mock.MagicMock()
    sys.modules["boto3"] = boto3_stub

try:
    from botocore.exceptions import ClientError
except ModuleNotFoundError:
    botocore_stub = types.ModuleType("botocore")
    exceptions_stub = types.ModuleType("botocore.exceptions")

    class ClientError(Exception):
        def __init__(self, error_response, operation_name):
            self.response = error_response
            self.operation_name = operation_name
            super().__init__(f"{operation_name}: {error_response}")

    exceptions_stub.ClientError = ClientError
    botocore_stub.exceptions = exceptions_stub
    sys.modules["botocore"] = botocore_stub
    sys.modules["botocore.exceptions"] = exceptions_stub

import lambda_function


def make_event(body, method="POST"):
    """Build an API Gateway HTTP API (payload v2.0) event."""
    if isinstance(body, (dict, list)):
        body = json.dumps(body)
    return {
        "version": "2.0",
        "requestContext": {"http": {"method": method}},
        "body": body,
    }


VALID_BOOKING = {
    "name":       "  Juan Pérez  ",
    "email":      "juan@ejemplo.com",
    "phone":      "(720) 555-0000",
    "event_date": "2026-08-01",
    "event_type": "wedding",
    "venue":      "Denver, CO",
    "message":    "Boda al aire libre",
}


class HandlerTest(unittest.TestCase):
    def setUp(self):
        # Fresh mocks per test so call assertions don't bleed across tests.
        lambda_function.ddb = mock.MagicMock()
        lambda_function.ses = mock.MagicMock()

    # ── Happy path ────────────────────────────────────────────────────
    def test_valid_booking_returns_200(self):
        res = lambda_function.handler(make_event(VALID_BOOKING), None)
        self.assertEqual(res["statusCode"], 200)
        self.assertEqual(json.loads(res["body"]), {"ok": True})

    def test_valid_booking_writes_to_dynamodb(self):
        lambda_function.handler(make_event(VALID_BOOKING), None)

        lambda_function.ddb.put_item.assert_called_once()
        item = lambda_function.ddb.put_item.call_args.kwargs["Item"]
        # Fields are trimmed and mapped to the table's camelCase keys.
        self.assertEqual(item["name"], "Juan Pérez")
        self.assertEqual(item["eventDate"], "2026-08-01")
        self.assertEqual(item["eventType"], "wedding")
        self.assertEqual(item["venue"], "Denver, CO")
        # An id and timestamp are generated server-side.
        self.assertTrue(item["id"])
        self.assertTrue(item["createdAt"])

    def test_valid_booking_sends_email_with_correct_roles(self):
        lambda_function.handler(make_event(VALID_BOOKING), None)

        lambda_function.ses.send_email.assert_called_once()
        kwargs = lambda_function.ses.send_email.call_args.kwargs
        self.assertEqual(kwargs["FromEmailAddress"], "bookings@djjohnnydenver.com")
        self.assertEqual(kwargs["Destination"]["ToAddresses"], ["djjohnny74@yahoo.com"])
        # Reply-To is the customer so Johnny can just hit reply.
        self.assertEqual(kwargs["ReplyToAddresses"], ["juan@ejemplo.com"])

    # ── Validation ────────────────────────────────────────────────────
    def test_missing_required_field_returns_400(self):
        for field in ("name", "email", "event_date", "event_type"):
            with self.subTest(missing=field):
                body = {**VALID_BOOKING}
                del body[field]
                res = lambda_function.handler(make_event(body), None)
                self.assertEqual(res["statusCode"], 400)
                lambda_function.ddb.put_item.assert_not_called()
                lambda_function.ses.send_email.assert_not_called()

    def test_malformed_email_returns_400(self):
        body = {**VALID_BOOKING, "email": "not-an-email"}
        res = lambda_function.handler(make_event(body), None)
        self.assertEqual(res["statusCode"], 400)

    def test_invalid_json_body_returns_400(self):
        res = lambda_function.handler(make_event("{not valid json"), None)
        self.assertEqual(res["statusCode"], 400)
        lambda_function.ddb.put_item.assert_not_called()

    def test_missing_body_returns_400(self):
        event = {"version": "2.0", "requestContext": {"http": {"method": "POST"}}}
        res = lambda_function.handler(event, None)
        self.assertEqual(res["statusCode"], 400)

    def test_non_object_json_body_returns_400(self):
        # Valid JSON, but not an object — must not crash with AttributeError.
        for body in ("123", '"hello"', "[1, 2, 3]", "null"):
            with self.subTest(body=body):
                res = lambda_function.handler(make_event(body), None)
                self.assertEqual(res["statusCode"], 400)
                lambda_function.ddb.put_item.assert_not_called()

    def test_non_string_field_does_not_crash(self):
        # A bot sending {"name": 5, ...} must get a clean 400, not a 500.
        body = {**VALID_BOOKING, "name": 5, "message": {"nested": "object"}}
        res = lambda_function.handler(make_event(body), None)
        # name=5 coerces to "5" (valid), message coerces to str — should store.
        self.assertEqual(res["statusCode"], 200)

    def test_invalid_event_type_returns_400(self):
        body = {**VALID_BOOKING, "event_type": "haxx"}
        res = lambda_function.handler(make_event(body), None)
        self.assertEqual(res["statusCode"], 400)
        lambda_function.ddb.put_item.assert_not_called()

    def test_invalid_event_date_format_returns_400(self):
        body = {**VALID_BOOKING, "event_date": "next tuesday"}
        res = lambda_function.handler(make_event(body), None)
        self.assertEqual(res["statusCode"], 400)

    def test_email_without_dot_returns_400(self):
        # The old weak check ("@" in email) let this through; the regex blocks it.
        body = {**VALID_BOOKING, "email": "juan@localhost"}
        res = lambda_function.handler(make_event(body), None)
        self.assertEqual(res["statusCode"], 400)

    def test_oversized_field_returns_400(self):
        body = {**VALID_BOOKING, "message": "x" * 2001}
        res = lambda_function.handler(make_event(body), None)
        self.assertEqual(res["statusCode"], 400)
        lambda_function.ddb.put_item.assert_not_called()

    # ── Honeypot ──────────────────────────────────────────────────────
    def test_honeypot_filled_is_silently_dropped(self):
        body = {**VALID_BOOKING, "website": "http://spam.example"}
        res = lambda_function.handler(make_event(body), None)
        # Pretends success so the bot gets no signal...
        self.assertEqual(res["statusCode"], 200)
        # ...but nothing is stored or emailed.
        lambda_function.ddb.put_item.assert_not_called()
        lambda_function.ses.send_email.assert_not_called()

    def test_empty_honeypot_is_accepted(self):
        body = {**VALID_BOOKING, "website": ""}
        res = lambda_function.handler(make_event(body), None)
        self.assertEqual(res["statusCode"], 200)
        lambda_function.ddb.put_item.assert_called_once()

    # ── CORS / preflight ──────────────────────────────────────────────
    def test_options_preflight_short_circuits(self):
        res = lambda_function.handler(make_event({}, method="OPTIONS"), None)
        self.assertEqual(res["statusCode"], 200)
        lambda_function.ddb.put_item.assert_not_called()
        lambda_function.ses.send_email.assert_not_called()

    def test_cors_header_on_every_response(self):
        for event in (
            make_event(VALID_BOOKING),                 # 200
            make_event({}),                            # 400
            make_event({}, method="OPTIONS"),          # 200 preflight
        ):
            res = lambda_function.handler(event, None)
            self.assertEqual(
                res["headers"]["Access-Control-Allow-Origin"],
                "https://djjohnnydenver.com",
            )

    # ── Failure handling ──────────────────────────────────────────────
    def test_ses_failure_returns_500(self):
        lambda_function.ses.send_email.side_effect = ClientError(
            {"Error": {"Code": "MessageRejected", "Message": "rejected"}},
            "SendEmail",
        )
        res = lambda_function.handler(make_event(VALID_BOOKING), None)
        self.assertEqual(res["statusCode"], 500)

    def test_dynamodb_failure_returns_500_and_skips_email(self):
        lambda_function.ddb.put_item.side_effect = ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "slow down"}},
            "PutItem",
        )
        res = lambda_function.handler(make_event(VALID_BOOKING), None)
        self.assertEqual(res["statusCode"], 500)
        lambda_function.ses.send_email.assert_not_called()


if __name__ == "__main__":
    unittest.main()
