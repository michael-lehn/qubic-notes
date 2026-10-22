"""Source positions and diagnostics."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Pos:
    line: int
    col: int


NOPOS = Pos(0, 0)


class QdError(Exception):
    def __init__(self, pos: Pos, msg: str, hint: str | None = None):
        super().__init__(msg)
        self.pos = pos
        self.msg = msg
        self.hint = hint


@dataclass
class Warning_:
    pos: Pos
    msg: str


@dataclass
class Diagnostics:
    filename: str
    source: str
    warnings: list = field(default_factory=list)

    def warn(self, pos: Pos, msg: str):
        self.warnings.append(Warning_(pos, msg))

    def _render(self, kind: str, pos: Pos, msg: str, hint: str | None = None) -> str:
        out = f'{self.filename}:{pos.line}:{pos.col}: {kind}: {msg}'
        lines = self.source.splitlines()
        if 0 < pos.line <= len(lines):
            text = lines[pos.line - 1]
            out += f'\n    {text}\n    {" " * (pos.col - 1)}^'
        if hint:
            out += '\n  hint: ' + hint.replace('\n', '\n        ')
        return out

    def format_error(self, err: QdError) -> str:
        return self._render('error', err.pos, err.msg, err.hint)

    def format_warnings(self) -> str:
        return '\n'.join(self._render('warning', w.pos, w.msg) for w in self.warnings)
