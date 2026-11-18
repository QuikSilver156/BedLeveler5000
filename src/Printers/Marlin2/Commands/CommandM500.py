from .WaitForOkCommand import WaitForOkCommand

class CommandM500(WaitForOkCommand):
    """ Save settings, including the bed mesh, to EEPROM. """
    NAME = 'M500'

    def __init__(self):
        super().__init__(self.NAME)
