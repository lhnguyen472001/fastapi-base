from typing import Generic, Protocol, runtime_checkable

from libs.database.sql.repository import RepositoryT
from libs.database.sql.types import SQLAlchemyModelT


@runtime_checkable
class BaseServiceProtocol(
    Protocol[SQLAlchemyModelT, RepositoryT],
    Generic[SQLAlchemyModelT, RepositoryT],
):
    """Protocol defining the base service interface.

    All services should implement this protocol to ensure consistent
    interaction with repositories and schema conversion.
    """

    repository: RepositoryT
    """The repository instance for data access."""

    def __init__(self, repository: RepositoryT) -> None:
        """Initialize service with repository.

        Args:
            repository: Repository instance for data access.
        """
