from .decorator import decorator_mode_8bit
# read/write/modify families are now code-generated (see opcodes_generated.py);
# only the irregular ops in other.py / pc.py are still called as functions.
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
