from .decorator import decorator_mode_8bit
from .read import *
from .write import *
from .other import *
from .pc import *


# TODO remove once all modes are implemented
def __getattr__(name: str):
    @decorator_mode_8bit
    def not_implemented(*args, **kwargs):
        raise NotImplementedError(name)
    try:
        return globals()[name]
    except KeyError:
        return not_implemented
