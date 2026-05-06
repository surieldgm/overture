import sqlite3
import tempfile
import unittest
from pathlib import Path

from overture.export_store import ExportLedger, ExportRecord, compute_hash


class ExportLedgerTests(unittest.TestCase):
    def test_constructor_creates_database_and_missing_find_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "nested" / "exports.sqlite"

            ledger = ExportLedger(db_path)

            self.assertTrue(db_path.exists())
            self.assertIsNone(ledger.find("tickets/example.md"))
            with sqlite3.connect(db_path) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM exports").fetchone()[0], 0)

    def test_record_round_trips_export_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = ExportLedger(Path(tmpdir) / "exports.sqlite")
            ticket_hash = compute_hash("# Ticket\n\nBody\n")

            ledger.record("tickets/example.md", ticket_hash, "issue-id-1", "https://linear.app/issue/ERI-1")
            record = ledger.find("tickets/example.md")

            self.assertIsInstance(record, ExportRecord)
            self.assertEqual(record.ticket_path, "tickets/example.md")
            self.assertEqual(record.ticket_hash, ticket_hash)
            self.assertEqual(record.linear_issue_id, "issue-id-1")
            self.assertEqual(record.linear_url, "https://linear.app/issue/ERI-1")
            self.assertRegex(record.exported_at, r"^\d{4}-\d{2}-\d{2}T.*Z$")

    def test_hash_detects_meaningful_ticket_changes(self) -> None:
        original_hash = compute_hash("# Ticket\n\nBody\n")
        changed_hash = compute_hash("# Ticket\n\nBody\n\n<!-- changed -->\n")

        self.assertNotEqual(original_hash, changed_hash)

    def test_hash_normalizes_line_endings_trailing_whitespace_and_final_newlines(self) -> None:
        lf_hash = compute_hash("# Ticket\n\nBody\n")
        crlf_hash = compute_hash("# Ticket  \r\n\r\nBody\t\r\n\r\n\r\n")

        self.assertEqual(lf_hash, crlf_hash)

    def test_record_upserts_same_path_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "exports.sqlite"
            ledger = ExportLedger(db_path)

            ledger.record(
                "tickets/example.md",
                compute_hash("# Ticket\n\nOld\n"),
                "issue-id-1",
                "https://linear.app/issue/ERI-1",
            )
            first_exported_at = ledger.find("tickets/example.md").exported_at
            ledger.record(
                "tickets/example.md",
                compute_hash("# Ticket\n\nNew\n"),
                "issue-id-2",
                "https://linear.app/issue/ERI-2",
            )

            record = ledger.find("tickets/example.md")
            self.assertEqual(record.ticket_hash, compute_hash("# Ticket\n\nNew\n"))
            self.assertEqual(record.linear_issue_id, "issue-id-2")
            self.assertEqual(record.linear_url, "https://linear.app/issue/ERI-2")
            self.assertGreaterEqual(record.exported_at, first_exported_at)
            with sqlite3.connect(db_path) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM exports").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
