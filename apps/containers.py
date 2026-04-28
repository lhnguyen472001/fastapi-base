from dependency_injector import containers, providers

from apps.auth.containers import AuthContainer
from apps.product.containers import ProductContainer
from apps.rbac.containers import RBACContainer
from apps.user.containers import UserContainer


class AppContainer(containers.DeclarativeContainer):
    auth: providers.Provider[AuthContainer] = providers.Container(AuthContainer)
    user: providers.Provider[UserContainer] = providers.Container(UserContainer)
    rbac: providers.Provider[RBACContainer] = providers.Container(RBACContainer)
    product: providers.Provider[ProductContainer] = providers.Container(ProductContainer)
