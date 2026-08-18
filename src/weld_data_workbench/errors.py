class WeldWorkbenchError(RuntimeError):
    """Base error for expected workbench failures."""


class ConfigurationError(WeldWorkbenchError):
    """Raised when a workspace configuration is invalid or missing."""


class DatasetDiscoveryError(WeldWorkbenchError):
    """Raised when no usable dataset content can be discovered."""


class IndexNotFoundError(WeldWorkbenchError):
    """Raised when an operation requires an index that does not exist."""


class UnsafeArchiveError(WeldWorkbenchError):
    """Raised when an archive member would escape the extraction directory."""
