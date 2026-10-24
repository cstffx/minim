from .literals import LiteralsMixin
from .operators import OperatorsMixin
from .access import AccessMixin
from .ctors import CtorsMixin
from .collections import CollectionsMixin
from .lists import ListsMixin
from .calls import CallsMixin
from .closures import ClosuresMixin
from .control import ControlMixin
from .runtime import RuntimeMixin
from .legacy import ExprMixinLegacy


class ExprMixin(LiteralsMixin, OperatorsMixin, AccessMixin, CtorsMixin,
                 CollectionsMixin, ListsMixin, CallsMixin, ClosuresMixin,
                 ControlMixin, RuntimeMixin, ExprMixinLegacy):
    pass
