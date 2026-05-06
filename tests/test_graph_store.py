import sqlite3
import tempfile
import unittest
from pathlib import Path

from overture.graph import GraphRecord
from overture.graph_store import SqliteGraphStore


class SqliteGraphStoreTests(unittest.TestCase):
    def test_first_upsert_creates_database_and_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "nested" / "graph.sqlite"
            store = SqliteGraphStore(db_path)

            self.assertFalse(db_path.exists())
            store.upsert_record(GraphRecord(kind="Source", key="source_docs", properties={"title": "Docs"}))

            self.assertTrue(db_path.exists())
            with sqlite3.connect(db_path) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM nodes").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT count(*) FROM edges").fetchone()[0], 0)

    def test_upsert_is_idempotent_for_nodes_and_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SqliteGraphStore(Path(tmpdir) / "graph.sqlite")
            records = (
                GraphRecord(kind="Source", key="source_docs", properties={"title": "Docs"}),
                GraphRecord(kind="ResearchItem", key="item_1", properties={"summary": "Read docs"}),
                GraphRecord(kind="Claim", key="claim_1", properties={"text": "SQLite is enough"}),
                GraphRecord(kind="CITES", key="item_1:cites:source_docs", properties={"from": "item_1", "to": "source_docs"}),
                GraphRecord(kind="HAS_CLAIM", key="item_1:has_claim:claim_1", properties={"from": "item_1", "to": "claim_1"}),
            )

            for _ in range(3):
                for record in records:
                    store.upsert_record(record)

            with sqlite3.connect(Path(tmpdir) / "graph.sqlite") as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM nodes").fetchone()[0], 3)
                self.assertEqual(connection.execute("SELECT count(*) FROM edges").fetchone()[0], 2)

    def test_load_context_round_trips_nodes_and_touching_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SqliteGraphStore(Path(tmpdir) / "graph.sqlite")
            store.upsert_record(GraphRecord(kind="Source", key="source_docs", properties={"title": "Docs"}))
            store.upsert_record(GraphRecord(kind="ResearchItem", key="item_1", properties={"summary": "Read docs"}))
            store.upsert_record(GraphRecord(kind="Claim", key="claim_1", properties={"text": "SQLite is enough"}))
            store.upsert_record(GraphRecord(kind="CITES", key="item_1:cites:source_docs", properties={"from": "item_1", "to": "source_docs"}))
            store.upsert_record(GraphRecord(kind="HAS_CLAIM", key="item_1:has_claim:claim_1", properties={"from": "item_1", "to": "claim_1"}))

            context = store.load_context()

            self.assertEqual({node["id"] for node in context.nodes}, {"source_docs", "item_1", "claim_1"})
            self.assertEqual({edge["type"] for edge in context.edges}, {"CITES", "HAS_CLAIM"})
            self.assertTrue(all(edge["from"] and edge["to"] for edge in context.edges))
            self.assertEqual(next(node for node in context.nodes if node["id"] == "source_docs")["title"], "Docs")

    def test_sequential_connections_can_read_after_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "graph.sqlite"
            first_store = SqliteGraphStore(db_path)
            first_store.upsert_record(GraphRecord(kind="Source", key="source_docs", properties={"title": "Docs"}))

            second_store = SqliteGraphStore(db_path)
            context = second_store.load_context()

            self.assertEqual(len(context.nodes), 1)
            self.assertEqual(context.nodes[0]["id"], "source_docs")


if __name__ == "__main__":
    unittest.main()
