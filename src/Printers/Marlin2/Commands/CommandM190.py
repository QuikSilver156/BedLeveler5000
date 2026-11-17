from .WaitForOkCommand import WaitForOkCommand
from . import Converter

class CommandM190(WaitForOkCommand):
    """ Set the bed temperature and wait until it is reached. """
    NAME = 'M190'

    def __init__(self, *, s):
        self.s = s
        super().__init__(self.NAME + Converter.floatToStr(self.s, prefix=' S'))
