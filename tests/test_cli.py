from __future__ import annotations

import unittest

from reveng.cli import parse_args


class CliTests(unittest.TestCase):
    def test_defaults_are_local_only(self) -> None:
        args = parse_args([])

        self.assertEqual("127.0.0.1", args.host)
        self.assertEqual(8080, args.port)
        self.assertFalse(args.reload)

    def test_explicit_server_options_are_parsed(self) -> None:
        args = parse_args(["--host", "localhost", "--port", "9000", "--reload"])

        self.assertEqual("localhost", args.host)
        self.assertEqual(9000, args.port)
        self.assertTrue(args.reload)


if __name__ == "__main__":
    unittest.main()
