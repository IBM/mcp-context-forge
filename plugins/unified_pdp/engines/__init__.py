"""Engine adapters – one module per back-end."""

from .cedar_engine import CedarEngineAdapter
from .mac_engine import MACEngineAdapter
from .native_engine import NativeRBACAdapter
from .opa_engine import OPAEngineAdapter

__all__ = [
    "OPAEngineAdapter",
    "CedarEngineAdapter",
    "NativeRBACAdapter",
    "MACEngineAdapter",
]
