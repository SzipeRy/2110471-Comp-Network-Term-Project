"""Message times are shown in the reader's own time zone (Person 2)."""
from datetime import datetime, timedelta, timezone
import unittest

from frontend.ui.chat_room import local_clock


class LocalClockTests(unittest.TestCase):
    def test_server_utc_time_is_shown_in_local_time(self):
        utc = datetime(2026, 11, 8, 5, 12, 30, 123000, tzinfo=timezone.utc)
        expected = utc.astimezone().strftime("%H:%M")  # e.g. 12:12 in Thailand (UTC+7)
        self.assertEqual(local_clock(utc.isoformat(timespec="milliseconds")), expected)

    def test_other_zones_are_converted_too(self):
        bangkok = datetime(2026, 11, 8, 12, 12, tzinfo=timezone(timedelta(hours=7)))
        self.assertEqual(local_clock(bangkok.isoformat()), bangkok.astimezone().strftime("%H:%M"))

    def test_time_without_a_zone_counts_as_local(self):  # the mock backend sends these
        self.assertEqual(local_clock("2026-11-08T12:12:30"), "12:12")

    def test_missing_or_broken_time_shows_nothing(self):
        for value in (None, "", "not a time"):
            self.assertEqual(local_clock(value), "")


if __name__ == "__main__":
    unittest.main()
