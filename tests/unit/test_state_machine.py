"""
Unit tests for the state machine — transition validation and audit behavior.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.onboarding_case import CaseSeverity, CaseStatus, OnboardingCase, SourceSystem
from app.services.state_machine import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    TransitionError,
    can_transition,
)


class TestCanTransition:
    def test_received_to_validating(self):
        assert can_transition(CaseStatus.RECEIVED, CaseStatus.VALIDATING) is True

    def test_validating_to_ready(self):
        assert can_transition(CaseStatus.VALIDATING, CaseStatus.READY_FOR_REMOTE) is True

    def test_validating_to_blocked(self):
        assert can_transition(CaseStatus.VALIDATING, CaseStatus.BLOCKED_VALIDATION) is True

    def test_blocked_to_validating(self):
        assert can_transition(CaseStatus.BLOCKED_VALIDATION, CaseStatus.VALIDATING) is True

    def test_ready_to_sync(self):
        assert can_transition(CaseStatus.READY_FOR_REMOTE, CaseStatus.REMOTE_SYNC_IN_PROGRESS) is True

    def test_sync_to_invited(self):
        assert can_transition(CaseStatus.REMOTE_SYNC_IN_PROGRESS, CaseStatus.REMOTE_INVITED) is True

    def test_onboarding_to_legal(self):
        assert can_transition(CaseStatus.REMOTE_ONBOARDING_IN_PROGRESS, CaseStatus.LEGAL_REVIEW_REQUIRED) is True

    def test_onboarding_to_completed(self):
        assert can_transition(CaseStatus.REMOTE_ONBOARDING_IN_PROGRESS, CaseStatus.COMPLETED) is True

    def test_waiting_to_completed(self):
        assert can_transition(CaseStatus.WAITING_ON_EMPLOYEE, CaseStatus.COMPLETED) is True

    # Invalid transitions
    def test_received_to_completed_invalid(self):
        assert can_transition(CaseStatus.RECEIVED, CaseStatus.COMPLETED) is False

    def test_validating_to_invited_invalid(self):
        assert can_transition(CaseStatus.VALIDATING, CaseStatus.REMOTE_INVITED) is False

    def test_completed_to_anything_invalid(self):
        for target in CaseStatus:
            assert can_transition(CaseStatus.COMPLETED, target) is False

    def test_cancelled_is_terminal(self):
        for target in CaseStatus:
            assert can_transition(CaseStatus.CANCELLED, target) is False

    def test_failed_terminal_is_terminal(self):
        for target in CaseStatus:
            assert can_transition(CaseStatus.FAILED_TERMINAL, target) is False


class TestTerminalStates:
    def test_completed_is_terminal(self):
        assert CaseStatus.COMPLETED in TERMINAL_STATES

    def test_cancelled_is_terminal(self):
        assert CaseStatus.CANCELLED in TERMINAL_STATES

    def test_failed_terminal_is_terminal(self):
        assert CaseStatus.FAILED_TERMINAL in TERMINAL_STATES

    def test_received_is_not_terminal(self):
        assert CaseStatus.RECEIVED not in TERMINAL_STATES


class TestTransitionCoverage:
    """Verify that all non-terminal states have at least one allowed transition."""

    def test_all_non_terminal_states_have_transitions(self):
        for status in CaseStatus:
            if status not in TERMINAL_STATES:
                assert status in ALLOWED_TRANSITIONS, f"{status} has no transitions defined"
                assert len(ALLOWED_TRANSITIONS[status]) > 0, f"{status} has empty transition set"


class TestEscalationTransitions:
    """Verify that escalated cases can return to operational states."""

    def test_escalated_can_return_to_validating(self):
        assert can_transition(CaseStatus.ESCALATED, CaseStatus.VALIDATING) is True

    def test_escalated_can_return_to_ready(self):
        assert can_transition(CaseStatus.ESCALATED, CaseStatus.READY_FOR_REMOTE) is True

    def test_escalated_can_be_cancelled(self):
        assert can_transition(CaseStatus.ESCALATED, CaseStatus.CANCELLED) is True
