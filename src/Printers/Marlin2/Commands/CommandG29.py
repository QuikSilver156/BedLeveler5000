from .WaitForOkCommand import WaitForOkCommand

class CommandG29(WaitForOkCommand):
    """ Automatic bed leveling: probe the full mesh grid (takes a few minutes). """
    NAME = 'G29'

    def __init__(self):
        super().__init__(self.NAME)
