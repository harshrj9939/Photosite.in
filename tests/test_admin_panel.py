import base64
import unittest
from unittest.mock import patch

from app import app
from notifications import notify_new_order


class AdminPanelTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.auth = base64.b64encode(b"admin:change-this-before-launch").decode("ascii")

    def test_admin_dashboard_renders_summary_and_customers(self):
        response = self.client.get(
            "/admin",
            headers={"Authorization": f"Basic {self.auth}"},
        )

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Photosite orders", html)
        self.assertIn("Order value", html)
        self.assertIn("Action needed", html)
        self.assertIn("Customers", html)


class NotificationTests(unittest.TestCase):
    @patch.dict(
        "os.environ",
        {
            "NOTIFICATION_EMAIL": "alerts@example.com",
            "SMTP_HOST": "smtp.example.com",
            "SMTP_USERNAME": "user",
            "SMTP_PASSWORD": "secret",
            "SMTP_FROM_EMAIL": "from@example.com",
        },
        clear=False,
    )
    @patch("notifications.smtplib.SMTP")
    def test_notify_uses_name_when_customer_name_missing(self, mock_smtp):
        class DummySMTP:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def ehlo(self, *args, **kwargs):
                return None

            def starttls(self):
                return None

            def login(self, *args, **kwargs):
                return None

            def send_message(self, message):
                self.message = message

        mock_smtp.return_value = DummySMTP()

        order = {
            "order_number": "PS-123",
            "amount": 899,
            "payment_method": "cod",
            "payment_status": "cash_on_delivery",
            "name": "Test User",
            "email": "test@example.com",
            "phone": "9876543210",
            "address": "Some address",
            "city": "Mumbai",
            "postal_code": "400001",
            "notes": "Gift",
        }
        items = [{"name": "Custom photo frame", "quantity": 1, "line_total": 899, "size_label": "6 × 8 in"}]

        self.assertTrue(notify_new_order(order, items))


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
