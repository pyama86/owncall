"""Tests for alert deduplication logic."""

import time
from unittest.mock import patch

from owncall.util.alert_dedup import AlertDeduplicator


class TestAlertDeduplicator:
    def test_first_message_is_not_duplicate(self):
        dedup = AlertDeduplicator(ttl_seconds=300)
        assert dedup.is_duplicate("High CPU usage on pod-123", "C001") is False

    def test_same_message_within_ttl_is_duplicate(self):
        dedup = AlertDeduplicator(ttl_seconds=300)
        dedup.record("High CPU usage on pod-123", "C001")
        assert dedup.is_duplicate("High CPU usage on pod-123", "C001") is True

    def test_different_message_is_not_duplicate(self):
        dedup = AlertDeduplicator(ttl_seconds=300)
        dedup.record("High CPU usage on pod-123", "C001")
        assert dedup.is_duplicate("Disk full on node-abc", "C001") is False

    def test_same_message_different_channel_is_not_duplicate(self):
        dedup = AlertDeduplicator(ttl_seconds=300)
        dedup.record("High CPU usage on pod-123", "C001")
        assert dedup.is_duplicate("High CPU usage on pod-123", "C002") is False

    def test_message_after_ttl_is_not_duplicate(self):
        dedup = AlertDeduplicator(ttl_seconds=10)
        base = time.monotonic()
        with patch("owncall.util.alert_dedup.time.monotonic", return_value=base):
            dedup.record("High CPU usage on pod-123", "C001")

        with patch("owncall.util.alert_dedup.time.monotonic", return_value=base + 11):
            assert dedup.is_duplicate("High CPU usage on pod-123", "C001") is False

    def test_messages_differing_only_in_numbers_are_duplicates(self):
        """Timestamps, metric values, and firing counts should be normalised away."""
        dedup = AlertDeduplicator(ttl_seconds=300)
        dedup.record("[FIRING:1] High CPU at 2024-01-15 12:00:00 value=95.3", "C001")
        assert (
            dedup.is_duplicate("[FIRING:3] High CPU at 2024-01-15 12:05:00 value=97.1", "C001")
            is True
        )

    def test_record_does_not_overwrite_existing_entry(self):
        """The first occurrence timestamp is preserved for TTL calculation."""
        dedup = AlertDeduplicator(ttl_seconds=10)
        base = time.monotonic()
        with patch("owncall.util.alert_dedup.time.monotonic", return_value=base):
            dedup.record("alert A", "C001")

        with patch("owncall.util.alert_dedup.time.monotonic", return_value=base + 5):
            dedup.record("alert A", "C001")

        # 11s after first record — should be expired even though second record was 6s ago
        with patch("owncall.util.alert_dedup.time.monotonic", return_value=base + 11):
            assert dedup.is_duplicate("alert A", "C001") is False

    def test_eviction_only_removes_expired(self):
        dedup = AlertDeduplicator(ttl_seconds=10)
        base = time.monotonic()
        with patch("owncall.util.alert_dedup.time.monotonic", return_value=base):
            dedup.record("alert A", "C001")
            dedup.record("alert B", "C001")

        with patch("owncall.util.alert_dedup.time.monotonic", return_value=base + 11):
            # Both should be expired
            assert dedup.is_duplicate("alert A", "C001") is False
            assert dedup.is_duplicate("alert B", "C001") is False
