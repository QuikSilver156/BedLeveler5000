from Printers.Marlin2.Commands.CommandG29 import CommandG29
from Printers.Marlin2.Commands.CommandM190 import CommandM190
from Printers.Marlin2.Commands.CommandM500 import CommandM500

G29_OUTPUT = ['echo:busy: processing',
              'Bed X: 35.00 Y: 25.00 Z: 0.04',
              'Bilinear Leveling Grid:',
              '      0      1      2',
              ' 0 +0.040 +0.010 -0.020',
              ' T:50.0 /50.0 B:50.0 /50.0 @:0 B@:0',
              'X:110.00 Y:110.00 Z:10.00 E:0.00 Count X:8800 Y:8800 Z:4000',
              'ok']

def runLines(command, lines):
    results = [command._processLine(line) for line in lines]
    return results

def test_G29WaitsForOk():
    command = CommandG29()
    assert command.request == 'G29'
    assert runLines(command, G29_OUTPUT) == [False] * (len(G29_OUTPUT) - 1) + [True]

def test_M190Request():
    command = CommandM190(s=50)
    assert command.request.startswith('M190 S50')
    assert runLines(command, [' T:30.0 /0.0 B:45.1 /50.0 @:0 B@:127', 'ok']) == [False, True]

def test_M500():
    command = CommandM500()
    assert command.request == 'M500'
    assert runLines(command, ['echo:Settings Stored (734 bytes; crc 12345)', 'ok']) == [False, True]

def test_ErrorRaises():
    from Printers.Marlin2.Commands.GCodeError import GCodeError
    command = CommandG29()
    try:
        command._processLine('Error:Probing Failed')
        assert False, 'expected GCodeError'
    except GCodeError:
        pass
