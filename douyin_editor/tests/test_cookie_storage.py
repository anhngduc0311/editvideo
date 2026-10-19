import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cookie_storage import CookieStorageError, protect_cookies, unprotect_cookies


@unittest.skipUnless(os.name == "nt", "Windows DPAPI")
class CookieStorageTests(unittest.TestCase):
    def test_encrypted_roundtrip_and_optional_timestamp(self):
        for timestamp in ("private-timestamp", ""):
            with self.subTest(timestamp=bool(timestamp)):
                encrypted = protect_cookies("private-session", timestamp)
                self.assertNotIn("private-session", encrypted)
                self.assertNotIn(b"private-session", base64.b64decode(encrypted.split(":", 2)[2]))
                self.assertEqual(unprotect_cookies(encrypted), ("private-session", timestamp))

    def test_decrypt_in_a_new_process(self):
        encrypted = protect_cookies("private-session", "private-timestamp")
        script = (
            "import sys; from cookie_storage import unprotect_cookies; "
            "assert unprotect_cookies(sys.stdin.read()) == ('private-session', 'private-timestamp'); print('OK')"
        )
        result = subprocess.run([sys.executable, "-c", script], input=encrypted, text=True,
                                capture_output=True, check=True, cwd=Path(__file__).resolve().parents[1], timeout=15)
        self.assertEqual(result.stdout.strip(), "OK")

    def test_corrupt_data_is_reported_without_credentials(self):
        for value in ("not-encrypted", "dpapi:v1:not-base64!", "dpapi:v1:" + base64.b64encode(b"invalid").decode()):
            with self.subTest(value=value), self.assertRaises(CookieStorageError):
                unprotect_cookies(value)


if __name__ == "__main__":
    unittest.main()
