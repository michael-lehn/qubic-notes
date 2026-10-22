"""Re-flow Markdown prose and list items to a maximum line width (default 80).

Code blocks, tables, headings and HTML lines are left untouched: they cannot be
wrapped without changing their meaning or rendering. Inline code spans and links
are never split.

    python tools/mdwrap.py [--width 80] [--check] FILE...
"""
import argparse
import re
import sys

FENCE = re.compile(r'^\s*(```|~~~)')
ITEM = re.compile(r'^(\s*)([-*+]|\d+[.)])(\s+)(\[[ xX]\]\s+)?')


def tokens(text: str) -> list[str]:
    """Split on spaces, keeping `code spans` and [links](targets) whole."""
    out, cur, i = [], '', 0
    in_code, bracket, paren = False, 0, 0
    while i < len(text):
        c = text[i]
        if c == '`':
            in_code = not in_code
        elif not in_code:
            if c == '[':
                bracket += 1
            elif c == ']' and bracket:
                bracket -= 1
                if bracket == 0 and i + 1 < len(text) and text[i + 1] == '(':
                    paren = 1
                    cur += c + '('
                    i += 2
                    continue
            elif paren:
                if c == '(':
                    paren += 1
                elif c == ')':
                    paren -= 1
        if c == ' ' and not in_code and not bracket and not paren:
            if cur:
                out.append(cur)
            cur = ''
        else:
            cur += c
        i += 1
    if cur:
        out.append(cur)
    return out


def starts_block(tok: str) -> bool:
    """Would a line starting with this token begin a new Markdown block?"""
    return (tok in ('-', '+', '*') or tok.startswith(('>', '|', '```', '~~~'))
            or re.fullmatch(r'#{1,6}|\d+[.)]|=+|-+', tok) is not None
            or re.match(r'<[A-Za-z/!]', tok) is not None)


def fill(text: str, first: str, rest: str, width: int) -> list[str]:
    """Greedy fill; never starts a continuation line with a block marker."""
    lines, words, prefix = [], [], first
    for tok in tokens(text):
        if words and len(prefix + ' '.join(words + [tok])) > width:
            carry = []
            while len(words) > 1 and starts_block(carry[0] if carry else tok):
                carry.insert(0, words.pop())
            lines.append(prefix + ' '.join(words))
            words, prefix = carry + [tok], rest
        else:
            words.append(tok)
    lines.append(prefix + ' '.join(words))
    return lines


def is_special(line: str) -> bool:
    s = line.strip()
    return (not s or s.startswith(('#', '|', '<', '>')) or re.match(r'^(-{3,}|\*{3,}|_{3,})$', s) is not None
            or bool(FENCE.match(line)))


def wrap(md: str, width: int) -> str:
    src = md.split('\n')
    out, i, fenced = [], 0, False
    while i < len(src):
        line = src[i]
        if FENCE.match(line):
            fenced = not fenced
            out.append(line)
            i += 1
            continue
        if fenced or is_special(line):
            out.append(line)
            i += 1
            continue
        m = ITEM.match(line)
        if m:
            marker = m.group(0)
            indent = ' ' * len(marker)
            body = [line[len(marker):].strip()]
            i += 1
            while i < len(src) and src[i].strip() and not is_special(src[i]) and not ITEM.match(src[i]) \
                    and src[i].startswith(indent[:max(len(m.group(1)) + 1, 1)]):
                body.append(src[i].strip())
                i += 1
            out += fill(' '.join(body), marker, indent, width)
            continue
        lead = re.match(r'^\s*', line).group(0)
        body = [line.strip()]
        i += 1
        while i < len(src) and src[i].strip() and not is_special(src[i]) and not ITEM.match(src[i]):
            body.append(src[i].strip())
            i += 1
        out += fill(' '.join(body), lead, lead, width)
    return '\n'.join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('files', nargs='+')
    ap.add_argument('--width', type=int, default=80)
    ap.add_argument('--check', action='store_true', help='report files that would change, write nothing')
    a = ap.parse_args()
    changed = 0
    for f in a.files:
        old = open(f).read()
        new = wrap(old, a.width)
        if new != old:
            changed += 1
            if a.check:
                print(f'would re-wrap {f}')
            else:
                open(f, 'w').write(new)
        long = sum(len(l) > a.width for l in new.split('\n'))
        print(f'{f}: {long} line(s) over {a.width} (tables, code blocks or unbreakable tokens)', file=sys.stderr)
    return 1 if a.check and changed else 0


if __name__ == '__main__':
    sys.exit(main())
