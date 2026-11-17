from .CommandBase import CommandBase
from .GCodeError import GCodeError

class WaitForOkCommand(CommandBase):
    """ For long-running commands (heat and wait, mesh probing, saving) whose output varies by
        firmware: every line is ignored until the final 'ok'. Marlin 'Error:' lines fail the command. """

    def _processLine(self, line):
        if line.startswith('ok'):
            return True
        if line.startswith('Error:') or line.startswith('!!'):
            raise GCodeError(f'The printer reported: {line}')
        return False
