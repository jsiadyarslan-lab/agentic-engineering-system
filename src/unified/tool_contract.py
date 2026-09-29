"""
Tool Contract — Unified Engineering Agents System

Formal contracts for all tools in the system.
Every tool has: input schema, output schema, permissions, timeout, retry policy,
risk level, audit event, and isolation requirements.

Based on: AgentFactory tools (filesystem, shell, git, web)
         EAS v2 tools (sandbox, grants, push)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Literal, Protocol, runtime_checkable
from pydantic import BaseModel, Field, field_validator
from dataclasses import dataclass


# ============================================================
# TOOL CLASSIFICATION
# ============================================================

class ToolCategory(str, Enum):
    """Tool categories."""
    FILESYSTEM = "filesystem"
    SHELL = "shell"
    GIT = "git"
    WEB = "web"
    SANDBOX = "sandbox"
    GRANT = "grant"
    PUSH = "push"
    ARTIFACT = "artifact"
    VERIFICATION = "verification"


class ToolRiskLevel(str, Enum):
    """Risk level for tool execution."""
    LOW = "low"           # Read-only, no side effects
    MEDIUM = "medium"     # Write within sandbox, bounded
    HIGH = "high"         # Shell execution, network, git push
    CRITICAL = "critical" # Host system modification, credentials


class IsolationRequirement(str, Enum):
    """Isolation requirement for tool."""
    NONE = "none"                    # Host execution OK
    SANDBOX = "sandbox"              # Must run in sandbox
    SANDBOX_WRITE = "sandbox_write"  # Write operations in sandbox only
    GRANT_GATED = "grant_gated"      # Requires valid grant


class RetryPolicy(BaseModel):
    """Retry configuration for tool."""
    max_retries: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    retry_on: List[str] = Field(default_factory=lambda: [
        "ConnectionError",
        "TimeoutError",
        "IOError",
        "RateLimitError",
    ])

    def get_delay(self, attempt: int) -> float:
        import random
        delay = min(
            self.base_delay_seconds * (self.exponential_base ** attempt),
            self.max_delay_seconds
        )
        if self.jitter:
            delay *= (0.5 + random.random() * 0.5)
        return delay


# ============================================================
# TOOL CONTRACTS
# ============================================================

class ToolInputSchema(BaseModel):
    """Base schema for tool inputs."""
    pass


class ToolOutputSchema(BaseModel):
    """Base schema for tool outputs."""
    success: bool
    output: Optional[Any] = None
    error: Optional[str] = None
    evidence_id: Optional[str] = None
    duration_ms: int = 0


class ToolContract(BaseModel):
    """
    Formal contract for a tool.
    Every tool in the system must have a registered contract.
    """
    name: str
    category: ToolCategory
    description: str

    # Schemas
    input_schema: type  # ToolInputSchema subclass
    output_schema: type  # ToolOutputSchema subclass

    # Permissions & Security
    required_permissions: List[str] = Field(default_factory=list)  # Grant types needed
    risk_level: ToolRiskLevel = ToolRiskLevel.LOW
    isolation: IsolationRequirement = IsolationRequirement.NONE

    # Execution
    timeout_seconds: int = 300
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)

    # Audit
    audit_event: str = ""  # EventType emitted on completion
    log_args: bool = True  # Whether to log arguments (sanitize secrets)
    log_output: bool = True

    # Behavior
    idempotent: bool = False
    side_effects: List[str] = Field(default_factory=list)

    @field_validator("audit_event")
    @classmethod
    def validate_audit_event(cls, v: str) -> str:
        if not v:
            # Auto-generate from name
            return f"tool.{v.lower().replace(' ', '_')}.completed"
        return v


# ============================================================
# FILESYSTEM TOOL CONTRACTS
# ============================================================

class ReadFileInput(ToolInputSchema):
    path: str
    encoding: str = "utf-8"
    max_bytes: Optional[int] = None


class ReadFileOutput(ToolOutputSchema):
    content: str = ""
    size_bytes: int = 0
    sha256: str = ""


READ_FILE_CONTRACT = ToolContract(
    name="read_file",
    category=ToolCategory.FILESYSTEM,
    description="Read file contents from workspace",
    input_schema=ReadFileInput,
    output_schema=ReadFileOutput,
    required_permissions=["read"],
    risk_level=ToolRiskLevel.LOW,
    isolation=IsolationRequirement.NONE,
    timeout_seconds=30,
    audit_event="tool.read_file.completed",
    idempotent=True,
)


class WriteFileInput(ToolInputSchema):
    path: str
    content: str
    encoding: str = "utf-8"
    overwrite: bool = False


class WriteFileOutput(ToolOutputSchema):
    path: str = ""
    size_bytes: int = 0
    sha256: str = ""


WRITE_FILE_CONTRACT = ToolContract(
    name="write_file",
    category=ToolCategory.FILESYSTEM,
    description="Write file to workspace (sandbox only for agents)",
    input_schema=WriteFileInput,
    output_schema=WriteFileOutput,
    required_permissions=["write"],
    risk_level=ToolRiskLevel.MEDIUM,
    isolation=IsolationRequirement.SANDBOX_WRITE,
    timeout_seconds=30,
    audit_event="tool.write_file.completed",
    side_effects=["file_created", "file_modified"],
)


class EditFileInput(ToolInputSchema):
    path: str
    old_text: str
    new_text: str
    replace_all: bool = False


class EditFileOutput(ToolOutputSchema):
    path: str = ""
    replacements: int = 0
    sha256: str = ""


EDIT_FILE_CONTRACT = ToolContract(
    name="edit_file",
    category=ToolCategory.FILESYSTEM,
    description="Edit file by replacing text",
    input_schema=EditFileInput,
    output_schema=EditFileOutput,
    required_permissions=["write"],
    risk_level=ToolRiskLevel.MEDIUM,
    isolation=IsolationRequirement.SANDBOX_WRITE,
    timeout_seconds=30,
    audit_event="tool.edit_file.completed",
    side_effects=["file_modified"],
)


class ListDirInput(ToolInputSchema):
    path: str = "."
    recursive: bool = False
    pattern: Optional[str] = None


class ListDirOutput(ToolOutputSchema):
    entries: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = 0


LIST_DIR_CONTRACT = ToolContract(
    name="list_dir",
    category=ToolCategory.FILESYSTEM,
    description="List directory contents",
    input_schema=ListDirInput,
    output_schema=ListDirOutput,
    required_permissions=["read"],
    risk_level=ToolRiskLevel.LOW,
    isolation=IsolationRequirement.NONE,
    timeout_seconds=30,
    audit_event="tool.list_dir.completed",
    idempotent=True,
)


class GrepInput(ToolInputSchema):
    pattern: str
    path: str = "."
    file_pattern: Optional[str] = None
    case_sensitive: bool = True
    max_results: int = 100


class GrepOutput(ToolOutputSchema):
    matches: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = 0


GREP_CONTRACT = ToolContract(
    name="grep",
    category=ToolCategory.FILESYSTEM,
    description="Search files for pattern",
    input_schema=GrepInput,
    output_schema=GrepOutput,
    required_permissions=["read"],
    risk_level=ToolRiskLevel.LOW,
    isolation=IsolationRequirement.NONE,
    timeout_seconds=60,
    audit_event="tool.grep.completed",
    idempotent=True,
)


class FindFilesInput(ToolInputSchema):
    pattern: str
    path: str = "."
    max_results: int = 100


class FindFilesOutput(ToolOutputSchema):
    files: List[str] = Field(default_factory=list)
    total: int = 0


FIND_FILES_CONTRACT = ToolContract(
    name="find_files",
    category=ToolCategory.FILESYSTEM,
    description="Find files by glob pattern",
    input_schema=FindFilesInput,
    output_schema=FindFilesOutput,
    required_permissions=["read"],
    risk_level=ToolRiskLevel.LOW,
    isolation=IsolationRequirement.NONE,
    timeout_seconds=30,
    audit_event="tool.find_files.completed",
    idempotent=True,
)


# ============================================================
# SHELL TOOL CONTRACT
# ============================================================

class RunCommandInput(ToolInputSchema):
    command: List[str]
    working_dir: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    timeout_seconds: int = 300
    capture_output: bool = True
    max_output_bytes: int = 1024 * 1024  # 1MB


class RunCommandOutput(ToolOutputSchema):
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    stdout_sha256: str = ""
    stderr_sha256: str = ""
    duration_ms: int = 0
    termination: str = ""


RUN_COMMAND_CONTRACT = ToolContract(
    name="run_command",
    category=ToolCategory.SHELL,
    description="Execute shell command in sandbox",
    input_schema=RunCommandInput,
    output_schema=RunCommandOutput,
    required_permissions=["execute"],
    risk_level=ToolRiskLevel.HIGH,
    isolation=IsolationRequirement.SANDBOX,
    timeout_seconds=300,
    retry_policy=RetryPolicy(max_retries=1),  # Limited retries for shell
    audit_event="tool.run_command.completed",
    log_args=True,
    log_output=True,
    side_effects=["process_execution", "file_changes", "network_access"],
)


# ============================================================
# GIT TOOL CONTRACTS
# ============================================================

class GitBranchInput(ToolInputSchema):
    action: Literal["list", "create", "checkout", "delete"]
    branch_name: Optional[str] = None
    start_point: Optional[str] = None
    repo_path: str = "."


class GitBranchOutput(ToolOutputSchema):
    branches: List[str] = Field(default_factory=list)
    current: str = ""
    created: bool = False


GIT_BRANCH_CONTRACT = ToolContract(
    name="git_branch",
    category=ToolCategory.GIT,
    description="Git branch operations",
    input_schema=GitBranchInput,
    output_schema=GitBranchOutput,
    required_permissions=["write"],
    risk_level=ToolRiskLevel.MEDIUM,
    isolation=IsolationRequirement.SANDBOX_WRITE,
    timeout_seconds=60,
    audit_event="tool.git_branch.completed",
    side_effects=["branch_created", "branch_deleted", "checkout"],
)


class GitCommitInput(ToolInputSchema):
    message: str
    files: Optional[List[str]] = None
    repo_path: str = "."
    author_name: Optional[str] = None
    author_email: Optional[str] = None


class GitCommitOutput(ToolOutputSchema):
    commit_hash: str = ""
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0


GIT_COMMIT_CONTRACT = ToolContract(
    name="git_commit",
    category=ToolCategory.GIT,
    description="Create git commit",
    input_schema=GitCommitInput,
    output_schema=GitCommitOutput,
    required_permissions=["write"],
    risk_level=ToolRiskLevel.MEDIUM,
    isolation=IsolationRequirement.SANDBOX_WRITE,
    timeout_seconds=60,
    audit_event="tool.git_commit.completed",
    side_effects=["commit_created"],
)


class GitDiffInput(ToolInputSchema):
    repo_path: str = "."
    staged: bool = False
    file_path: Optional[str] = None


class GitDiffOutput(ToolOutputSchema):
    diff: str = ""
    files_changed: int = 0


GIT_DIFF_CONTRACT = ToolContract(
    name="git_diff",
    category=ToolCategory.GIT,
    description="Show git diff",
    input_schema=GitDiffInput,
    output_schema=GitDiffOutput,
    required_permissions=["read"],
    risk_level=ToolRiskLevel.LOW,
    isolation=IsolationRequirement.NONE,
    timeout_seconds=30,
    audit_event="tool.git_diff.completed",
    idempotent=True,
)


class GitStatusInput(ToolInputSchema):
    repo_path: str = "."


class GitStatusOutput(ToolOutputSchema):
    clean: bool = True
    staged: List[str] = Field(default_factory=list)
    unstaged: List[str] = Field(default_factory=list)
    untracked: List[str] = Field(default_factory=list)


GIT_STATUS_CONTRACT = ToolContract(
    name="git_status",
    category=ToolCategory.GIT,
    description="Show git status",
    input_schema=GitStatusInput,
    output_schema=GitStatusOutput,
    required_permissions=["read"],
    risk_level=ToolRiskLevel.LOW,
    isolation=IsolationRequirement.NONE,
    timeout_seconds=30,
    audit_event="tool.git_status.completed",
    idempotent=True,
)


# ============================================================
# WEB TOOL CONTRACTS
# ============================================================

class WebSearchInput(ToolInputSchema):
    query: str
    max_results: int = 10
    recency_days: Optional[int] = None


class WebSearchOutput(ToolOutputSchema):
    results: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = 0


WEB_SEARCH_CONTRACT = ToolContract(
    name="web_search",
    category=ToolCategory.WEB,
    description="Search the web",
    input_schema=WebSearchInput,
    output_schema=WebSearchOutput,
    required_permissions=["read"],
    risk_level=ToolRiskLevel.LOW,
    isolation=IsolationRequirement.NONE,
    timeout_seconds=30,
    audit_event="tool.web_search.completed",
    idempotent=True,
)


class WebFetchInput(ToolInputSchema):
    url: str
    max_bytes: int = 1024 * 1024  # 1MB


class WebFetchOutput(ToolOutputSchema):
    content: str = ""
    content_type: str = ""
    url: str = ""


WEB_FETCH_CONTRACT = ToolContract(
    name="web_fetch",
    category=ToolCategory.WEB,
    description="Fetch web page content",
    input_schema=WebFetchInput,
    output_schema=WebFetchOutput,
    required_permissions=["read"],
    risk_level=ToolRiskLevel.LOW,
    isolation=IsolationRequirement.NONE,
    timeout_seconds=30,
    audit_event="tool.web_fetch.completed",
    side_effects=["network_request"],
)


class FileBrowserInput(ToolInputSchema):
    path: str = "."
    show_hidden: bool = False


class FileBrowserOutput(ToolOutputSchema):
    tree: Dict[str, Any] = Field(default_factory=dict)
    total_files: int = 0
    total_dirs: int = 0


FILE_BROWSER_CONTRACT = ToolContract(
    name="file_browser",
    category=ToolCategory.FILESYSTEM,
    description="Browse file tree structure",
    input_schema=FileBrowserInput,
    output_schema=FileBrowserOutput,
    required_permissions=["read"],
    risk_level=ToolRiskLevel.LOW,
    isolation=IsolationRequirement.NONE,
    timeout_seconds=30,
    audit_event="tool.file_browser.completed",
    idempotent=True,
)


# ============================================================
# SANDBOX TOOL CONTRACTS (EAS v2)
# ============================================================

class SandboxExecuteInput(ToolInputSchema):
    sandbox_id: str
    image: str
    command: List[str]
    working_dir: str = "/workspace"
    artifacts_dir: str = "/artifacts"
    sources_root: str = ""
    memory_bytes: Optional[int] = None
    cpu_percent: Optional[float] = None
    wall_time_seconds: int = 300
    required_grant_ids: List[str] = Field(default_factory=list)


class SandboxExecuteOutput(ToolOutputSchema):
    exit_code: Optional[int] = None
    termination: str = ""
    duration_ms: int = 0
    stdout_sha256: str = ""
    stderr_sha256: str = ""
    artifacts: List[str] = Field(default_factory=list)  # artifact_ids
    evidence_hash: str = ""


SANDBOX_EXECUTE_CONTRACT = ToolContract(
    name="sandbox_execute",
    category=ToolCategory.SANDBOX,
    description="Execute command in isolated sandbox",
    input_schema=SandboxExecuteInput,
    output_schema=SandboxExecuteOutput,
    required_permissions=["execute"],
    risk_level=ToolRiskLevel.HIGH,
    isolation=IsolationRequirement.SANDBOX,
    timeout_seconds=300,
    audit_event="tool.sandbox_execute.completed",
    side_effects=["process_execution", "artifact_creation", "resource_consumption"],
)


class ArtifactWriteInput(ToolInputSchema):
    sandbox_id: str
    path: str  # Relative to /artifacts
    content: str
    encoding: str = "utf-8"


class ArtifactWriteOutput(ToolOutputSchema):
    artifact_id: str = ""
    path: str = ""
    sha256: str = ""
    size_bytes: int = 0


ARTIFACT_WRITE_CONTRACT = ToolContract(
    name="artifact_write",
    category=ToolCategory.ARTIFACT,
    description="Write artifact to sandbox custody directory",
    input_schema=ArtifactWriteInput,
    output_schema=ArtifactWriteOutput,
    required_permissions=["write"],
    risk_level=ToolRiskLevel.MEDIUM,
    isolation=IsolationRequirement.SANDBOX_WRITE,
    timeout_seconds=30,
    audit_event="tool.artifact_write.completed",
    side_effects=["artifact_created"],
)


class ArtifactReadInput(ToolInputSchema):
    sandbox_id: str
    path: str  # Relative to /artifacts


class ArtifactReadOutput(ToolOutputSchema):
    content: str = ""
    sha256: str = ""
    size_bytes: int = 0


ARTIFACT_READ_CONTRACT = ToolContract(
    name="artifact_read",
    category=ToolCategory.ARTIFACT,
    description="Read artifact from sandbox custody directory",
    input_schema=ArtifactReadInput,
    output_schema=ArtifactReadOutput,
    required_permissions=["read"],
    risk_level=ToolRiskLevel.LOW,
    isolation=IsolationRequirement.SANDBOX,
    timeout_seconds=30,
    audit_event="tool.artifact_read.completed",
    idempotent=True,
)


class VerificationCheckInput(ToolInputSchema):
    task_acceptance_criteria: List[str]
    artifacts: List[str]  # artifact paths
    evidence_refs: List[str]


class VerificationCheckOutput(ToolOutputSchema):
    verdict: Literal["evidenced", "not_evidenced"]
    checks_performed: List[str] = Field(default_factory=list)
    missing_evidence: List[str] = Field(default_factory=list)
    confidence: float = 0.0


VERIFICATION_CHECK_CONTRACT = ToolContract(
    name="verification_check",
    category=ToolCategory.VERIFICATION,
    description="Verify artifacts against acceptance criteria",
    input_schema=VerificationCheckInput,
    output_schema=VerificationCheckOutput,
    required_permissions=["read", "execute"],
    risk_level=ToolRiskLevel.LOW,
    isolation=IsolationRequirement.SANDBOX,
    timeout_seconds=60,
    audit_event="tool.verification_check.completed",
    idempotent=True,
)


# ============================================================
# GRANT TOOL CONTRACTS
# ============================================================

class GrantValidateInput(ToolInputSchema):
    grant_id: str
    subject: str
    required_permission: str
    required_resource: str


class GrantValidateOutput(ToolOutputSchema):
    valid: bool
    reason: Optional[str] = None
    grant_details: Optional[Dict[str, Any]] = None


GRANT_VALIDATE_CONTRACT = ToolContract(
    name="grant_validate",
    category=ToolCategory.GRANT,
    description="Validate grant for admission/execution",
    input_schema=GrantValidateInput,
    output_schema=GrantValidateOutput,
    required_permissions=[],
    risk_level=ToolRiskLevel.LOW,
    isolation=IsolationRequirement.NONE,
    timeout_seconds=10,
    audit_event="tool.grant_validate.completed",
    idempotent=True,
)


# ============================================================
# PUSH TOOL CONTRACT
# ============================================================

class GitPushInput(ToolInputSchema):
    repo_path: str
    remote: str = "origin"
    branch: str
    force: bool = False
    owner_approval_nonce: str  # Required for push


class GitPushOutput(ToolOutputSchema):
    pushed: bool = False
    commit_hash: str = ""
    remote_ref: str = ""
    certificates: List[str] = Field(default_factory=list)


GIT_PUSH_CONTRACT = ToolContract(
    name="git_push",
    category=ToolCategory.PUSH,
    description="Push to git remote with owner approval",
    input_schema=GitPushInput,
    output_schema=GitPushOutput,
    required_permissions=["write", "admin"],
    risk_level=ToolRiskLevel.CRITICAL,
    isolation=IsolationRequirement.GRANT_GATED,
    timeout_seconds=120,
    retry_policy=RetryPolicy(max_retries=1),
    audit_event="tool.git_push.completed",
    side_effects=["remote_push", "certificate_creation"],
)


# ============================================================
# TOOL REGISTRY
# ============================================================

ALL_TOOL_CONTRACTS: Dict[str, ToolContract] = {
    # Filesystem
    "read_file": READ_FILE_CONTRACT,
    "write_file": WRITE_FILE_CONTRACT,
    "edit_file": EDIT_FILE_CONTRACT,
    "list_dir": LIST_DIR_CONTRACT,
    "grep": GREP_CONTRACT,
    "find_files": FIND_FILES_CONTRACT,
    "file_browser": FILE_BROWSER_CONTRACT,

    # Shell
    "run_command": RUN_COMMAND_CONTRACT,

    # Git
    "git_branch": GIT_BRANCH_CONTRACT,
    "git_commit": GIT_COMMIT_CONTRACT,
    "git_diff": GIT_DIFF_CONTRACT,
    "git_status": GIT_STATUS_CONTRACT,
    "git_push": GIT_PUSH_CONTRACT,

    # Web
    "web_search": WEB_SEARCH_CONTRACT,
    "web_fetch": WEB_FETCH_CONTRACT,

    # Sandbox (EAS v2)
    "sandbox_execute": SANDBOX_EXECUTE_CONTRACT,
    "artifact_write": ARTIFACT_WRITE_CONTRACT,
    "artifact_read": ARTIFACT_READ_CONTRACT,
    "verification_check": VERIFICATION_CHECK_CONTRACT,

    # Grants
    "grant_validate": GRANT_VALIDATE_CONTRACT,

    # Push
    "git_push": GIT_PUSH_CONTRACT,
}


class ToolRegistry:
    """Registry of all tool contracts."""

    def __init__(self):
        self.contracts = ALL_TOOL_CONTRACTS.copy()

    def get(self, name: str) -> Optional[ToolContract]:
        """Get tool contract by name."""
        return self.contracts.get(name)

    def register(self, contract: ToolContract) -> None:
        """Register new tool contract."""
        if contract.name in self.contracts:
            raise ValueError(f"Tool {contract.name} already registered")
        self.contracts[contract.name] = contract

    def unregister(self, name: str) -> None:
        """Unregister tool contract."""
        if name not in self.contracts:
            raise ValueError(f"Tool {name} not registered")
        del self.contracts[name]

    def list_by_category(self, category: ToolCategory) -> List[ToolContract]:
        """List tools by category."""
        return [c for c in self.contracts.values() if c.category == category]

    def list_by_permission(self, permission: str) -> List[ToolContract]:
        """List tools requiring a permission."""
        return [c for c in self.contracts.values() if permission in c.required_permissions]

    def list_by_risk(self, risk: ToolRiskLevel) -> List[ToolContract]:
        """List tools by risk level."""
        return [c for c in self.contracts.values() if c.risk_level == risk]

    def list_by_isolation(self, isolation: IsolationRequirement) -> List[ToolContract]:
        """List tools by isolation requirement."""
        return [c for c in self.contracts.values() if c.isolation == isolation]

    def validate_input(self, tool_name: str, input_data: Dict) -> bool:
        """Validate input against tool contract."""
        contract = self.get(tool_name)
        if not contract:
            return False
        try:
            contract.input_schema.model_validate(input_data)
            return True
        except Exception:
            return False

    def validate_output(self, tool_name: str, output_data: Dict) -> bool:
        """Validate output against tool contract."""
        contract = self.get(tool_name)
        if not contract:
            return False
        try:
            contract.output_schema.model_validate(output_data)
            return True
        except Exception:
            return False


# ============================================================
# TOOL EXECUTION CONTEXT
# ============================================================

class ToolExecutionContext(BaseModel):
    """Context passed to tool execution."""
    mission_id: str
    run_id: str
    task_id: str
    attempt_id: str
    agent_id: str
    agent_type: str
    grant_ids: List[str] = Field(default_factory=list)
    workspace_root: str = "."
    sandbox_id: Optional[str] = None
    token_budget_remaining: int = 50000


class ToolResult(BaseModel):
    """Result of tool execution with audit info."""
    tool_name: str
    success: bool
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    evidence_id: Optional[str] = None
    duration_ms: int = 0
    audit_event: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    # Enums
    "ToolCategory",
    "ToolRiskLevel",
    "IsolationRequirement",
    # Schemas
    "ToolInputSchema",
    "ToolOutputSchema",
    "RetryPolicy",
    "ToolContract",
    # Filesystem
    "ReadFileInput", "ReadFileOutput", "READ_FILE_CONTRACT",
    "WriteFileInput", "WriteFileOutput", "WRITE_FILE_CONTRACT",
    "EditFileInput", "EditFileOutput", "EDIT_FILE_CONTRACT",
    "ListDirInput", "ListDirOutput", "LIST_DIR_CONTRACT",
    "GrepInput", "GrepOutput", "GREP_CONTRACT",
    "FindFilesInput", "FindFilesOutput", "FIND_FILES_CONTRACT",
    "FileBrowserInput", "FileBrowserOutput", "FILE_BROWSER_CONTRACT",
    # Shell
    "RunCommandInput", "RunCommandOutput", "RUN_COMMAND_CONTRACT",
    # Git
    "GitBranchInput", "GitBranchOutput", "GIT_BRANCH_CONTRACT",
    "GitCommitInput", "GitCommitOutput", "GIT_COMMIT_CONTRACT",
    "GitDiffInput", "GitDiffOutput", "GIT_DIFF_CONTRACT",
    "GitStatusInput", "GitStatusOutput", "GIT_STATUS_CONTRACT",
    "GitPushInput", "GitPushOutput", "GIT_PUSH_CONTRACT",
    # Web
    "WebSearchInput", "WebSearchOutput", "WEB_SEARCH_CONTRACT",
    "WebFetchInput", "WebFetchOutput", "WEB_FETCH_CONTRACT",
    # Sandbox
    "SandboxExecuteInput", "SandboxExecuteOutput", "SANDBOX_EXECUTE_CONTRACT",
    "ArtifactWriteInput", "ArtifactWriteOutput", "ARTIFACT_WRITE_CONTRACT",
    "ArtifactReadInput", "ArtifactReadOutput", "ARTIFACT_READ_CONTRACT",
    "VerificationCheckInput", "VerificationCheckOutput", "VERIFICATION_CHECK_CONTRACT",
    # Grants
    "GrantValidateInput", "GrantValidateOutput", "GRANT_VALIDATE_CONTRACT",
    # Registry
    "ALL_TOOL_CONTRACTS",
    "ToolRegistry",
    # Context
    "ToolExecutionContext",
    "ToolResult",
]