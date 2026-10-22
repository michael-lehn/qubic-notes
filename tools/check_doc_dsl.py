"""Check that every QD snippet in docs/reference.md is valid QD.

- ```odin blocks: complete programs, compiled by the QD front end and QubiC.
- `QD ...` lines in code blocks (with 5-space continuation lines): complete
  programs, compiled; if the block also lists machine words (`@n <32 hex>`),
  every listed word must appear in the compiled program.
- Inline code in table columns titled QD or Construct, and in the
  'Five shortcomings' list when it looks like code (an identifier plus ';',
  '{' or '('): fragments, checked against the grammar.

Blocks fenced as ```text (the superseded original sketch) and the
'Original construct' column are deliberately not QD and are skipped.

    python tools/check_doc_dsl.py [FILE.md ...]     (default: docs/reference.md)
"""
import logging
import re
import sys

from qdsl import backend
from qdsl.cli import front_end, quiet_qubic
from qdsl.diag import QdError
from qdsl.syntax import parse
from qdsl.target import Target

PRELUDE = 'qubit Q0, Q1, Q2;\n'
WORD = re.compile(r'^@\d+\s+([0-9a-f]{32})\b', re.M)


def looks_like_code(text: str) -> bool:
    return re.search(r'[A-Za-z_]', text) is not None and re.search(r'[;{(]', text) is not None


def grammar_error(fragment: str):
    code = fragment if fragment.rstrip().endswith((';', '}')) else fragment + ';'
    try:
        parse(PRELUDE + code)
    except QdError as e:
        return e.msg
    return None


def compile_error(program: str, target: Target, listed: list[int]):
    try:
        ir, _ = front_end(program, 'doc', target)
        words = {w for ws in backend.build(ir, target).words().values() for w in ws}
    except QdError as e:
        return f'line {e.pos.line}: {e.msg}'
    except Exception as e:                                   # QubiC compile/assemble failure
        return f'{type(e).__name__}: {e}'
    missing = [f'{w:032x}' for w in listed if w not in words]
    return f'{len(missing)} listed word(s) not produced, e.g. {missing[0]}' if missing else None


def snippets(md: str):
    """Yield (line, kind, code, listed_words); listed_words is None for fragments."""
    lines = md.split('\n')
    i, qd_cols, in_shortcomings = 0, set(), False
    while i < len(lines):
        line = lines[i]
        m = re.match(r'^```(\w*)', line)
        if m:
            lang, start, body = m.group(1), i + 2, []
            i += 1
            while i < len(lines) and not lines[i].startswith('```'):
                body.append(lines[i])
                i += 1
            if lang == 'odin':
                yield start, 'odin block', '\n'.join(body), []
            listed = [int(h, 16) for h in WORD.findall('\n'.join(body))]
            for k, b in enumerate(body):
                if b.startswith('QD '):
                    prog = [b[3:].strip()]
                    for c in body[k + 1:]:
                        if not c.startswith('     '):
                            break
                        prog.append(c.strip())
                    yield start + k, 'QD line', '\n'.join(prog), listed
            i += 1
            continue
        if line.startswith('#'):
            in_shortcomings = 'shortcomings' in line.lower()
        if line.startswith('|'):
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            if any(c in ('QD', 'Construct', 'Original construct') for c in cells):
                qd_cols = {k for k, c in enumerate(cells) if c in ('QD', 'Construct')}
            elif not all(re.fullmatch(r':?-+:?', c) for c in cells):
                for k in qd_cols:
                    for code in re.findall(r'`([^`]+)`', cells[k] if k < len(cells) else ''):
                        if looks_like_code(code):
                            yield i + 1, 'table', code, None
        else:
            qd_cols = set()
            if in_shortcomings:
                for code in re.findall(r'`([^`]+)`', line):
                    if looks_like_code(code):
                        yield i + 1, 'shortcomings', code, None
        i += 1


def main() -> int:
    quiet_qubic()
    logging.disable(logging.WARNING)
    paths = sys.argv[1:] or ['docs/reference.md']
    target = Target()
    bad = total = 0
    for path, (line, kind, code, listed) in ((p, s) for p in paths for s in snippets(open(p).read())):
        total += 1
        err = grammar_error(code) if listed is None else compile_error(code, target, listed)
        bad += err is not None
        one = ' '.join(code.split())
        print(f'{"ok  " if err is None else "FAIL"} {path}:{line:<4d} {kind:12s} {one[:50]}'
              + (f'\n           -> {err}' if err else ''))
    print(f'{total} snippets, {bad} not valid QD')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
