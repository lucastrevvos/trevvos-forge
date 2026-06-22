class ForgeError(Exception):
    """Base exception for all Trevvos Forge errors."""


class ProviderError(ForgeError):
    """Base exception for provider-related errors."""


class ProviderConnectionError(ProviderError):
    """Raised when a provider cannot be reached."""


class ProviderTimeoutError(ProviderError):
    """Raised when a provider request times out."""


class ProviderResponseError(ProviderError):
    """Raised when a provider returns an invalid or unexpected response."""


class ProviderHttpError(ProviderError):
    """Raised when a provider returns an HTTP error."""


class ConfigurationError(ForgeError):
    """Raised when Trevvos Forge configuration is invalid."""


class WorkspaceError(ForgeError):
    """Raised when workspace access or validation fails."""


class SessionError(ForgeError):
    """Raised when session management fails."""


class PromptError(ForgeError):
    """Raised when prompt rendering or prompt lookup fails."""


class StructuredOutputError(ForgeError):
    """Raised when an LLM structured output is invalid."""


class FileChangeOutputError(ForgeError):
    """Raised when structured file change output is invalid."""


class DiffError(ForgeError):
    """Raised when diff generation or parsing fails."""


class RepairNotRepairableError(DiffError):
    """Raised when repair is requested for a session without repairable diff evidence."""


class DiffValidationError(DiffError):
    """Raised when a generated diff fails safety validation."""


class ApplyError(ForgeError):
    """Raised when applying a validated diff fails."""


class TestRunError(ForgeError):
    """Raised when configured validation commands cannot be run."""


class CommitError(ForgeError):
    """Raised when assisted commit planning or execution fails."""
