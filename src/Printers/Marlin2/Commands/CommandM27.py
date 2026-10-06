from .CommandBase import CommandBase

class CommandM27(CommandBase):
    """ Report SD print status. Used to refuse leveling while the printer is printing from its SD card. """
    NAME = 'M27'

    def __init__(self):
        super().__init__(self.NAME)

    def _processLine(self, line):
        # Line 0: 'Not SD printing' or 'SD printing byte 1234/5678' (absent without SD support)
        # Line 1: ok

        if line.startswith('ok'):
            self.verifyOkResponseLine(line)
            if self.result is None:
                self.result = {'printing': False, 'detail': ''}
            return True

        if line.startswith('SD printing byte'):
            self.result = {'printing': True, 'detail': line.strip()}
        elif line.startswith('Not SD printing'):
            self.result = {'printing': False, 'detail': line.strip()}
        # Anything else (echo:, auto-reports, 'Unknown command' without SD support) is ignored

        return False
