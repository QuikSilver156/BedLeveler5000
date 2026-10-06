from Printers.Marlin2.Commands.CommandM27 import CommandM27
from dataclasses import dataclass, field
import pytest

@dataclass(frozen=True)
class TestPoint:
    __test__ = False
    lines: [str]
    expected: dict = field(default=None)

testPoints = [
    TestPoint(lines = ['Not SD printing', 'ok'],
              expected = {'printing': False, 'detail': 'Not SD printing'}),
    TestPoint(lines = ['SD printing byte 1234/5678', 'ok'],
              expected = {'printing': True, 'detail': 'SD printing byte 1234/5678'}),
    TestPoint(lines = ['echo:Unknown command: "M27"', 'ok'],
              expected = {'printing': False, 'detail': ''}),
    TestPoint(lines = [' T:28.0 /0.0 B:27.0 /0.0 @:0 B@:0', 'Not SD printing', 'ok P15 B3'],
              expected = {'printing': False, 'detail': 'Not SD printing'})
    ]

@pytest.mark.parametrize('testPoint', testPoints)
def test_VerifyCorrect(testPoint):
    command = CommandM27()
    for index, line in enumerate(testPoint.lines):
        result = command._processLine(line)
        isLast = index == len(testPoint.lines) - 1
        assert(isLast == result)
    assert(command.result == testPoint.expected)
