from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class EventType(str, Enum):
    # ─── Development pipeline ──────────────────────────────
    GOAL_CREATED               = "goal.created"
    TASKS_DECOMPOSED           = "tasks.decomposed"
    SPEC_COMPLETED             = "spec.completed"
    REPO_CREATED               = "repo.created"
    CODE_COMMITTED             = "code.committed"
    PR_OPENED                  = "pr.opened"
    QA_PASSED                  = "qa.passed"
    QA_FAILED                  = "qa.failed"
    FIX_ATTEMPTED              = "fix.attempted"
    FIX_EXHAUSTED              = "fix.exhausted"
    SECURITY_PASSED            = "security.passed"
    SECURITY_BLOCKED           = "security.blocked"
    DEPLOYED_STAGING           = "deployed.staging"
    SMOKE_PASSED               = "smoke.passed"
    SMOKE_FAILED               = "smoke.failed"
    DEPLOYED_PRODUCTION        = "deployed.production"
    HUMAN_INTERVENTION_REQUIRED = "human.intervention.required"

    # ─── Marketing pipeline ────────────────────────────────
    VIDEO_REQUESTED            = "video.requested"
    SCRIPT_COMPLETED           = "script.completed"
    VOICE_COMPLETED            = "voice.completed"
    VISUAL_COMPLETED           = "visual.completed"
    MUSIC_COMPLETED            = "music.completed"
    VIDEO_ASSEMBLED            = "video.assembled"
    COMPLIANCE_APPROVED        = "compliance.approved"
    COMPLIANCE_REJECTED        = "compliance.rejected"
    VIDEO_PUBLISHED            = "video.published"
    ADS_CAMPAIGN_LAUNCHED      = "ads.campaign.launched"

    # ─── Infra / Cost ──────────────────────────────────────
    LLM_USAGE_RECORDED         = "llm.usage.recorded"
    BUDGET_THRESHOLD_80        = "budget.threshold.80"
    BUDGET_THRESHOLD_100       = "budget.threshold.100"
    BUDGET_EXHAUSTED           = "budget.exhausted"

    # ─── Security / Ops ────────────────────────────────────
    INCIDENT_DETECTED          = "incident.detected"
    VULNERABILITY_FOUND        = "vulnerability.found"
    HEALTHCHECK_FAILED         = "healthcheck.failed"
    SELF_IMPROVEMENT_REPORT    = "self.improvement.report"

    # ─── Cost Gate ─────────────────────────────────────────
    COST_APPROVAL_REQUESTED    = "cost.approval.requested"
    COST_APPROVAL_DECIDED      = "cost.approval.decided"


class AgentStatus(str, Enum):
    IDLE    = "idle"
    WORKING = "working"
    WAITING = "waiting"
    FAILED  = "failed"
    STOPPED = "stopped"


class CostDecision(str, Enum):
    GREEN = "green"    # < $0.50 → auto-proceed
    AMBER = "amber"    # $0.50–$5.00 → WhatsApp approval
    RED   = "red"      # > $5.00 → block


class Event(BaseModel):
    id:             str = Field(default_factory=lambda: str(uuid4()))
    type:           EventType
    publisher:      str
    payload:        dict[str, Any] = Field(default_factory=dict)
    timestamp:      datetime = Field(default_factory=datetime.utcnow)
    correlation_id: str | None = None


class CostPreviewItem(BaseModel):
    agent:          str
    model:          str
    estimated_cost: float
    description:    str


class CostPreview(BaseModel):
    goal:           str
    items:          list[CostPreviewItem]
    total_min:      float
    total_max:      float
    budget_remaining: float
    fits_budget:    bool


class TaskAssignment(BaseModel):
    task_id:        str
    goal:           str
    spec_url:       str | None = None
    repo_url:       str | None = None
    pr_number:      int | None = None
    max_fix_attempts: int = 5
    metadata:       dict[str, Any] = Field(default_factory=dict)


class QAReport(BaseModel):
    task_id:        str
    passed:         bool
    unit_pass:      bool
    integration_pass: bool
    e2e_pass:       bool
    coverage_line:  float
    coverage_branch: float
    lint_errors:    int
    type_errors:    int
    failed_tests:   list[str] = Field(default_factory=list)
    stack_traces:   list[str] = Field(default_factory=list)


class SecurityReport(BaseModel):
    task_id:        str
    passed:         bool
    sast_findings:  list[dict] = Field(default_factory=list)
    cve_findings:   list[dict] = Field(default_factory=list)
    secrets_found:  list[dict] = Field(default_factory=list)
    max_cvss:       float = 0.0
