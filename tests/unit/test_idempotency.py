"""
Unit tests for idempotency key generation.
"""

from app.core.idempotency import generate_idempotency_key, generate_workflow_id


class TestIdempotencyKey:
    def test_deterministic(self):
        key1 = generate_idempotency_key("remote_create", "ONB-123", "jane@example.com")
        key2 = generate_idempotency_key("remote_create", "ONB-123", "jane@example.com")
        assert key1 == key2

    def test_different_inputs_differ(self):
        key1 = generate_idempotency_key("remote_create", "ONB-123", "jane@example.com")
        key2 = generate_idempotency_key("remote_create", "ONB-456", "jane@example.com")
        assert key1 != key2

    def test_length(self):
        key = generate_idempotency_key("test", "data")
        assert len(key) == 32

    def test_single_part(self):
        key = generate_idempotency_key("only_one_part")
        assert len(key) == 32


class TestWorkflowId:
    def test_with_sequence(self):
        wid = generate_workflow_id(sequence=42)
        assert wid == "ONB-000042"

    def test_without_sequence(self):
        wid = generate_workflow_id()
        assert wid.startswith("ONB-")
        assert len(wid) == 12  # "ONB-" + 8 hex chars

    def test_unique_without_sequence(self):
        ids = {generate_workflow_id() for _ in range(100)}
        assert len(ids) == 100
