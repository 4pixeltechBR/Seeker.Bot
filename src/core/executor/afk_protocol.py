"""
AFK Protocol Coordinator for Remote Executor.

AFKProtocolCoordinator:
    Tracks user online/offline status.
    Manages approval queue for L0_MANUAL actions.
    Handles escalation and timeout logic.
    Enforces AFK window constraints for L1_LOGGED actions.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from dataclasses import dataclass, field

from .models import ActionStep, AutonomyTier, ActionStatus

logger = logging.getLogger("seeker.executor.afk_protocol")


@dataclass
class ApprovalRequest:
    """Pending approval request for L0_MANUAL action."""
    action_id: str
    step: ActionStep
    created_at: datetime = field(default_factory=datetime.utcnow)
    timeout_at: datetime = field(default_factory=lambda: datetime.utcnow() + timedelta(seconds=300))
    retry_count: int = 0
    max_retries: int = 3

    @property
    def is_expired(self) -> bool:
        """Check if approval request has expired."""
        return datetime.utcnow() > self.timeout_at

    @property
    def time_until_timeout(self) -> int:
        """Time until timeout in seconds."""
        remaining = (self.timeout_at - datetime.utcnow()).total_seconds()
        return max(0, int(remaining))


class AFKProtocolCoordinator:
    """
    Coordinates AFK (Away From Keyboard) protocol.

    Responsibilities:
    1. Track user status (online/AFK, time since last activity)
    2. Queue L0_MANUAL approval requests
    3. Handle approval/rejection callbacks
    4. Manage timeout and retry logic
    5. Escalate unresponded requests (Telegram + Email)
    6. Enforce AFK window for L1_LOGGED actions
    """

    def __init__(self, user_id: str = "default"):
        """
        Initialize coordinator.

        Args:
            user_id: User ID to track
        """
        self.user_id = user_id
        self.last_seen_at = datetime.utcnow()  # Assume online when created
        self.approval_queue: Dict[str, ApprovalRequest] = {}  # action_id → ApprovalRequest
        self.approval_responses: Dict[str, bool] = {}  # action_id → (True=approved, False=rejected)
        self.audit_log: List[dict] = []

    @property
    def is_afk(self) -> bool:
        """Check if user is currently AFK."""
        # TODO: Phase B3 - integrate with actual presence detection
        # For now, assume not AFK (will be updated by external signals)
        return False

    @property
    def afk_time_seconds(self) -> int:
        """Time user has been AFK in seconds."""
        if self.is_afk:
            return int((datetime.utcnow() - self.last_seen_at).total_seconds())
        return 0

    async def mark_online(self):
        """Mark user as online (activity detected)."""
        self.last_seen_at = datetime.utcnow()
        logger.info(f"[afk] User {self.user_id} marked online")

    async def enqueue_approval(self, step: ActionStep) -> str:
        """
        Enqueue L0_MANUAL action for approval.

        Args:
            step: L0_MANUAL ActionStep

        Returns:
            approval_id (same as action_id)

        Raises:
            ValueError: If step is not L0_MANUAL
        """
        if step.approval_tier != AutonomyTier.L0_MANUAL:
            raise ValueError(f"Only L0_MANUAL actions can be enqueued, got {step.approval_tier}")

        approval = ApprovalRequest(action_id=step.id, step=step)
        self.approval_queue[step.id] = approval

        self.audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": "enqueue_approval",
            "action_id": step.id,
            "step_type": step.type.value,
            "description": step.description,
        })

        logger.info(f"[afk] L0 approval enqueued: {step.id} ({step.description})")
        return step.id

    async def respond_to_approval(self, action_id: str, approved: bool) -> bool:
        """
        User responds to approval request.

        Args:
            action_id: Which approval to respond to
            approved: True to approve, False to reject

        Returns:
            True if response processed, False if not found/expired
        """
        if action_id not in self.approval_queue:
            logger.warning(f"[afk] Approval request not found: {action_id}")
            return False

        approval = self.approval_queue[action_id]

        if approval.is_expired:
            logger.warning(f"[afk] Approval request expired: {action_id}")
            return False

        self.approval_responses[action_id] = approved
        del self.approval_queue[action_id]

        self.audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": "respond_to_approval",
            "action_id": action_id,
            "approved": approved,
            "retry_count": approval.retry_count,
        })

        status = "APPROVED" if approved else "REJECTED"
        logger.info(f"[afk] L0 approval {status}: {action_id}")
        return True

    async def check_approval_status(self, action_id: str) -> Optional[bool]:
        """
        Check if approval has been responded to.

        Args:
            action_id: Which approval to check

        Returns:
            True if approved, False if rejected, None if pending
        """
        return self.approval_responses.get(action_id)

    async def get_pending_approvals(self) -> List[ApprovalRequest]:
        """Get list of pending approval requests."""
        # Remove expired approvals
        expired_ids = [
            aid for aid, approval in self.approval_queue.items()
            if approval.is_expired
        ]

        for aid in expired_ids:
            approval = self.approval_queue.pop(aid)
            self.audit_log.append({
                "timestamp": datetime.utcnow().isoformat(),
                "action": "approval_timeout",
                "action_id": aid,
                "retry_count": approval.retry_count,
            })

            if approval.retry_count < approval.max_retries:
                # Re-enqueue for retry
                approval.retry_count += 1
                approval.timeout_at = datetime.utcnow() + timedelta(seconds=300)
                self.approval_queue[aid] = approval
                logger.info(
                    f"[afk] Approval retry {approval.retry_count}/{approval.max_retries}: {aid}"
                )

        return list(self.approval_queue.values())

    async def escalate_approval(self, action_id: str) -> bool:
        """
        Escalate approval request (send Telegram + Email notifications).

        Args:
            action_id: Which approval to escalate

        Returns:
            True if escalation sent
        """
        if action_id not in self.approval_queue:
            return False

        approval = self.approval_queue[action_id]

        self.audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": "escalate_approval",
            "action_id": action_id,
            "retry_count": approval.retry_count,
            "channels": ["telegram", "email"],
        })

        logger.info(f"[afk] Escalating approval: {action_id}")
        # TODO: Phase B3 - actually send Telegram + Email
        return True

    async def enforce_afk_window(
        self, step: ActionStep, afk_window_hours: int
    ) -> bool:
        """
        Check if L1_LOGGED action respects AFK window.

        Args:
            step: ActionStep (should be L1_LOGGED)
            afk_window_hours: Max AFK time allowed (e.g., 12)

        Returns:
            True if action is within AFK window, False if exceeded
        """
        if step.approval_tier != AutonomyTier.L1_LOGGED:
            return True  # Only applies to L1

        afk_hours = self.afk_time_seconds / 3600

        if afk_hours > afk_window_hours:
            logger.warning(
                f"[afk] L1 action exceeds AFK window ({afk_hours:.1f}h > {afk_window_hours}h)"
            )
            return False

        return True

    def get_audit_log(self) -> List[dict]:
        """Get coordination audit log."""
        return self.audit_log.copy()

    def clear_audit_log(self):
        """Clear audit log."""
        self.audit_log = []
