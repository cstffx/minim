from .layouts import BIRLayoutsMixin
from .places import BIRPlacesMixin
from .rvalues import BIRRvaluesMixin
from .aggregates import BIRAggregatesMixin
from .calls import BIRCallsMixin
from .cfg import BIRCFGMixin
from .legacy import BIRCodegenLegacy


class BIRCodegen(BIRLayoutsMixin, BIRPlacesMixin, BIRRvaluesMixin,
                  BIRAggregatesMixin, BIRCallsMixin, BIRCFGMixin,
                  BIRCodegenLegacy):
    pass
