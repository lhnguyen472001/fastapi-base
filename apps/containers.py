from dependency_injector import containers, providers

from libs.database.sql.engine import engine_factory
from libs.database.sql.session import session_factory


class CoreContainer(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(
        packages=["apps.libs.database.sql.repositories"],
    )

    engine = providers.Singleton(engine_factory)
    session = providers.Singleton(session_factory)
