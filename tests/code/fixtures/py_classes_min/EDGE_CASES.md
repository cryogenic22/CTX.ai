# py_classes_min — edge cases pinned

Fixture for CP-004 (class method + class attribute extraction).
Each line below documents what the corresponding piece of
`widget.py` is testing. Don't simplify the fixture without first
moving the test that depends on it.

| Line | Element | Pins |
|---|---|---|
| `class Widget:` | Class with a body | Walker descends into `class_definition.body` |
| `MAX_TICKS = 100` | Untyped class attribute (plain assignment) | Detected as `CLASS_ATTRIBUTE`, name `Widget.MAX_TICKS` |
| `name: str = ""` | Typed class attribute with default | Detected as `CLASS_ATTRIBUTE`, name `Widget.name` |
| `def __init__(...)` | Dunder method | Extracted (the walker does NOT skip dunders) |
| `def tick(...)` | Regular instance method | Extracted as `METHOD`, name `Widget.tick` |
| `@property age` | Property getter | Walker descends through `decorated_definition` |
| `@age.setter` | Setter with same name as getter | TWO `Widget.age` METHOD symbols (no dedup at CP-004; CP-005 carries the decorator distinction) |
| `@staticmethod identity` | Static method | Extracted as plain METHOD; staticness lives in decorator metadata (CP-005) |
| `@classmethod from_dict` | Classmethod | Same — METHOD; classmethodness lives in decorators |
| `async def refresh` | Async method | Still METHOD; async lives on the function_definition node (not affecting Kind) |
| `def __repr__` | Another dunder, end of class body | Walker doesn't truncate after first dunder |

Total expected symbol count when extracting `widget.py`:

  1 CLASS  + 2 CLASS_ATTRIBUTE + 8 METHOD = 11 symbols

(`age` appears twice — once as getter, once as setter — hence 8
method entries from 7 visible `def` lines.)
