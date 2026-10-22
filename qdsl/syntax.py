"""AST and parser (Lark LALR, grammar in grammar.lark)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lark import Lark, Transformer, v_args, Token
from lark.exceptions import UnexpectedInput

from .diag import Pos, QdError


# ---------------------------------------------------------------- expressions

@dataclass
class Num:
    value: float | int
    pos: Pos


@dataclass
class Quantity:          # 500 us, 4.9 GHz
    value: float
    unit: str
    pos: Pos


@dataclass
class Pi:
    pos: Pos


@dataclass
class Str:
    value: str
    pos: Pos


@dataclass
class Name:
    id: str
    pos: Pos


@dataclass
class Attr:              # Q0.qdrv, Q0.freq
    base: str
    attr: str
    pos: Pos


@dataclass
class Arg:
    name: str | None
    value: object
    pos: Pos


@dataclass
class Call:
    func: str
    args: list[Arg]
    pos: Pos


@dataclass
class Neg:
    operand: object
    pos: Pos


@dataclass
class BinOp:
    op: str
    lhs: object
    rhs: object
    pos: Pos


@dataclass
class Cond:
    op: str
    lhs: object
    rhs: object
    pos: Pos


# ---------------------------------------------------------------- declarations / statements

@dataclass
class QubitDecl:
    names: list[str]
    pos: Pos


@dataclass
class ConstDecl:
    name: str
    type: str | None
    value: object
    pos: Pos


@dataclass
class VarDecl:
    name: str
    type: str | None
    init: object | None
    pos: Pos


@dataclass
class ProcDecl:
    name: str
    params: list[tuple[str, str]]
    body: Block
    pos: Pos


@dataclass
class Assign:
    target: str
    op: str
    value: object
    pos: Pos


@dataclass
class CallStmt:
    call: Call
    pos: Pos


@dataclass
class If:
    cond: Cond
    then: Block
    els: Block | If | None
    pos: Pos


@dataclass
class DoWhile:
    body: Block
    cond: Cond
    pos: Pos


@dataclass
class ForCond:
    cond: Cond
    body: Block
    pos: Pos


@dataclass
class ForRange:
    var: str
    lo: object
    hi: object
    body: Block
    pos: Pos


@dataclass
class Unroll:
    var: str
    values: list | None          # explicit list, or
    lo: object = None            # lo ..< hi step s
    hi: object = None
    step: object = None
    body: Block = None
    pos: Pos = None


@dataclass
class Par:
    branches: list[Block]
    pos: Pos


@dataclass
class Block:
    items: list
    pos: Pos


@dataclass
class Program:
    items: list


# ---------------------------------------------------------------- parse tree -> AST

def _pos(meta_or_tok) -> Pos:
    return Pos(getattr(meta_or_tok, 'line', 0), getattr(meta_or_tok, 'column', 0))


@v_args(meta=True)
class _ToAST(Transformer):
    def start(self, meta, items):
        return Program(items)

    # declarations
    def qubit_decl(self, meta, names):
        return QubitDecl([str(n) for n in names], _pos(meta))

    def type(self, meta, children):
        return str(children[0])

    def const_typed(self, meta, c):
        return ConstDecl(str(c[0]), c[1], c[2], _pos(meta))

    def const_inferred(self, meta, c):
        return ConstDecl(str(c[0]), None, c[1], _pos(meta))

    def var_init(self, meta, c):
        return VarDecl(str(c[0]), c[1], c[2], _pos(meta))

    def var_zero(self, meta, c):
        return VarDecl(str(c[0]), c[1], None, _pos(meta))

    def var_inferred(self, meta, c):
        return VarDecl(str(c[0]), None, c[1], _pos(meta))

    def param(self, meta, c):
        return (str(c[0]), c[1])

    def proc_decl(self, meta, c):
        name, *params, body = c
        return ProcDecl(str(name), [p for p in params if p is not None], body, _pos(meta))

    # statements
    def assign(self, meta, c):
        return Assign(str(c[0]), str(c[1]), c[2], _pos(meta))

    def call_stmt(self, meta, c):
        return CallStmt(c[0], _pos(meta))

    def if_stmt(self, meta, c):
        return If(c[0], c[1], c[2] if len(c) > 2 else None, _pos(meta))

    def do_stmt(self, meta, c):
        return DoWhile(c[0], c[1], _pos(meta))

    def for_cond(self, meta, c):
        return ForCond(c[0], c[1], _pos(meta))

    def for_range(self, meta, c):
        return ForRange(str(c[0]), c[1], c[2], c[3], _pos(meta))

    def unroll_list(self, meta, c):
        return ('list', c)

    def unroll_range(self, meta, c):
        return ('range', c)

    def unroll(self, meta, c):
        var, (kind, seq), body = c
        if kind == 'list':
            return Unroll(str(var), seq, body=body, pos=_pos(meta))
        lo, hi, step = (seq + [None])[:3]
        return Unroll(str(var), None, lo, hi, step, body, _pos(meta))

    def par(self, meta, blocks):
        return Par(blocks, _pos(meta))

    def block(self, meta, items):
        return Block(items, _pos(meta))

    def cond(self, meta, c):
        return Cond(str(c[1]), c[0], c[2], _pos(meta))

    # expressions
    def binop(self, meta, c):
        return BinOp(str(c[1]), c[0], c[2], _pos(meta))

    def neg(self, meta, c):
        return Neg(c[0], _pos(meta))

    def quantity(self, meta, c):
        return Quantity(float(c[0]), str(c[1]), _pos(meta))

    def number(self, meta, c):
        text = str(c[0])
        value = int(text) if text.isdigit() else float(text)
        return Num(value, _pos(meta))

    def pi(self, meta, c):
        return Pi(_pos(meta))

    def string(self, meta, c):
        return Str(str(c[0])[1:-1], _pos(meta))

    def attr(self, meta, c):
        return Attr(str(c[0]), str(c[1]), _pos(meta))

    def name(self, meta, c):
        return Name(str(c[0]), _pos(meta))

    def pos_arg(self, meta, c):
        return Arg(None, c[0], _pos(meta))

    def kw_arg(self, meta, c):
        return Arg(str(c[0]), c[1], _pos(meta))

    def call(self, meta, c):
        return Call(str(c[0]), [a for a in c[1:] if a is not None], _pos(meta))


_GRAMMAR = (Path(__file__).parent / 'grammar.lark').read_text()
_PARSER = Lark(_GRAMMAR, parser='lalr', propagate_positions=True, maybe_placeholders=True)


def _show(terminal: str) -> str:
    try:
        pat = _PARSER.get_terminal(terminal).pattern
    except KeyError:
        return terminal
    return f"'{pat.value}'" if pat.type == 'str' else terminal.lower()


def parse(source: str) -> Program:
    try:
        tree = _PARSER.parse(source)
    except UnexpectedInput as e:
        expected = sorted({_show(t) for t in (getattr(e, 'expected', None) or getattr(e, 'allowed', None) or [])})
        hint = ('expected ' + ' or '.join(expected[:10])) if expected else None
        tok = getattr(e, 'token', None)
        what = f"unexpected '{tok}'" if isinstance(tok, Token) else 'syntax error'
        raise QdError(Pos(e.line, e.column), what, hint) from None
    return _ToAST().transform(tree)
