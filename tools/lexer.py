"""Lexer for Minim (.mim). Emits INDENT/DEDENT/NEWLINE like Python."""

import re

KEYWORDS = {
    "use", "let", "var", "fn", "type", "case", "trait",
    "if", "elif", "else", "for", "in", "while", "break", "continue",
    "return", "match", "and", "or", "not", "is", "as", "self", "it",
    "move", "spawn", "await", "true", "false", "nil",
}

# Multi-char operators (longest first)
MULTI_OPS = [
    "==", "!=", "<=", ">=", "<<", ">>", "**", "//", "..=", "..",
    "+=", "-=", "*=", "/=", "%=", "**=", "->", "=>",
]

SINGLE_OPS = set("+-*/%&|^~<>?=.,:;()[]{}!")


class Token:
    __slots__ = ("type", "value", "line", "col")

    def __init__(self, type_, value, line, col):
        self.type = type_
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self):
        return f"Token({self.type!r}, {self.value!r}, {self.line}, {self.col})"


class LexerError(Exception):
    pass


def tokenize(source):
    tokens = []
    lines = source.split("\n")
    # Remove trailing empty from final newline
    # We'll process line by line with indentation tracking.

    indent_stack = [0]
    bracket_depth = 0  # inside () [] {} -> no INDENT/DEDENT/NEWLINE

    i = 0
    n_lines = len(lines)

    # We process with an index over lines, handling multi-line strings.
    # Simpler: iterate character by character with line tracking.

    # Approach: build a list of (line, col, char) and process with state machine.
    # But indentation needs line-level logic. Let's do line-based with a tokenizer per line.

    # First, handle the whole source as lines.
    # We need to handle MLSTR (""") which can span lines.

    # Let's pre-process: tokenize line by line, but MLSTR/FSTR need care.
    # Simpler approach: character-level scanner.

    src = source
    pos = 0
    line = 1
    col = 1
    # We'll emit tokens. Indentation handled at line starts.

    # Track whether we're at the start of a line (for indentation)
    at_line_start = True
    # pending indentation to process
    # We'll handle indentation when we encounter first non-space/tab on a line.

    def emit(ttype, tval, ln, cl):
        tokens.append(Token(ttype, tval, ln, cl))

    # Helper to skip whitespace (spaces) - tabs handled as indentation
    # We need to handle indentation specially.

    # Let's do a manual scan.
    length = len(src)

    # State for bracket depth
    bd = 0

    # We need line-start detection. Let's track position and handle newlines.
    # Process character by character.

    # Buffer for current line's leading whitespace
    # We'll handle indentation when at_line_start and not in brackets.

    idx = 0
    cur_line = 1
    cur_col = 1

    # We'll collect the output tokens. Need to handle indentation before content.

    # Strategy: split into lines first, but handle MLSTR specially.
    # Actually, let's do a hybrid: process line by line.

    # First, split source into "logical lines" handling MLSTR.
    # MLSTR: """ ... """ can span multiple lines. When inside MLSTR, don't process indentation.

    # Let's just do a character scanner with proper state.

    i = 0
    L = len(src)
    line_no = 1
    col_no = 1

    # We'll accumulate tokens. Indentation processed at line starts.

    def current_indent_level():
        return indent_stack[-1]

    # We need to know if at start of line
    at_bol = True  # beginning of line
    # leading whitespace buffer
    leading_ws = ""

    # We'll process char by char
    while i < L:
        c = src[i]

        # Handle newline
        if c == "\n":
            # End of line
            if bracket_depth == 0:
                # Emit NEWLINE if there's content on this line (not blank)
                # We need to know if the line had tokens. Check last token.
                if tokens and tokens[-1].type not in ("NEWLINE", "INDENT", "DEDENT"):
                    emit("NEWLINE", "\\n", line_no, col_no)
            # Reset line state
            i += 1
            line_no += 1
            col_no = 1
            at_bol = True
            leading_ws = ""
            continue

        # Handle carriage return
        if c == "\r":
            i += 1
            continue

        # At beginning of line: handle indentation (only if not in brackets)
        if at_bol:
            if c == " " or c == "\t":
                leading_ws += c
                i += 1
                col_no += 1
                continue
            # Non-whitespace: process indentation
            at_bol = False
            if bracket_depth == 0:
                # Count tabs in leading_ws. Minim requires INDENT = tabs only;
                # mixing spaces and tabs in leading indentation is a lexer error.
                if " " in leading_ws and "\t" in leading_ws:
                    raise LexerError(
                        f"Mixing spaces and tabs in indentation at line {line_no}"
                    )
                tabs = 0
                for ch in leading_ws:
                    if ch == "\t":
                        tabs += 1
                # Compare with indent stack
                if tabs > indent_stack[-1]:
                    # Need to emit one INDENT per tab level increase
                    # Minim: one tab = one level. So if tabs = current + 1, one INDENT.
                    # If jumped multiple levels, emit multiple.
                    while tabs > indent_stack[-1]:
                        indent_stack.append(indent_stack[-1] + 1)
                        emit("INDENT", "\t", line_no, 1)
                elif tabs < indent_stack[-1]:
                    while tabs < indent_stack[-1]:
                        indent_stack.pop()
                        emit("DEDENT", "", line_no, 1)
                    if tabs != indent_stack[-1]:
                        raise LexerError(f"Indentation error at line {line_no}")
            leading_ws = ""
            # Fall through to process c

        # Skip spaces (not at bol)
        if c == " ":
            i += 1
            col_no += 1
            continue

        # Tab in middle of line (not indentation) - skip? or error. Skip.
        if c == "\t" and not at_bol:
            i += 1
            col_no += 1
            continue

        # Comments
        if c == "#":
            # skip to end of line
            while i < L and src[i] != "\n":
                i += 1
            # don't emit newline here; the \n handler will
            continue

        ln = line_no
        cl = col_no

        # Multi-line string """
        if c == '"' and i + 2 < L and src[i:i+3] == '"""':
            # MLSTR
            start = i
            i += 3
            col_no += 3
            buf = ""
            while i < L:
                if src[i:i+3] == '"""':
                    i += 3
                    col_no += 3
                    break
                if src[i] == "\n":
                    line_no += 1
                    col_no = 1
                    buf += "\n"
                    i += 1
                else:
                    buf += src[i]
                    i += 1
                    col_no += 1
            emit("MLSTR", buf, ln, cl)
            continue

        # Raw string r"..." or r'...'
        if c == "r" and i + 1 < L and src[i+1] in ('"', "'"):
            quote = src[i+1]
            i += 2
            col_no += 2
            buf = ""
            while i < L and src[i] != quote:
                buf += src[i]
                i += 1
                col_no += 1
            if i < L:
                i += 1
                col_no += 1
            emit("RSTR", buf, ln, cl)
            continue

        # Bytes b"..." or b'...'
        if c == "b" and i + 1 < L and src[i+1] in ('"', "'"):
            quote = src[i+1]
            i += 2
            col_no += 2
            buf = ""
            while i < L and src[i] != quote:
                if src[i] == "\\":
                    buf += src[i:i+2]
                    i += 2
                    col_no += 2
                else:
                    buf += src[i]
                    i += 1
                    col_no += 1
            if i < L:
                i += 1
                col_no += 1
            emit("BYTES", buf, ln, cl)
            continue

        # f-string f"..."
        if c == "f" and i + 1 < L and src[i+1] in ('"', "'"):
            quote = src[i+1]
            i += 2
            col_no += 2
            buf = ""
            # read until closing quote, handling escapes and braces
            while i < L and src[i] != quote:
                if src[i] == "\\":
                    buf += src[i:i+2]
                    i += 2
                    col_no += 2
                else:
                    buf += src[i]
                    i += 1
                    col_no += 1
            if i < L:
                i += 1
                col_no += 1
            emit("FSTR", buf, ln, cl)
            continue

        # Regular string "..." or '...'
        if c in ('"', "'"):
            quote = c
            i += 1
            col_no += 1
            buf = ""
            while i < L and src[i] != quote and src[i] != "\n":
                if src[i] == "\\":
                    buf += src[i:i+2]
                    i += 2
                    col_no += 2
                else:
                    buf += src[i]
                    i += 1
                    col_no += 1
            if i < L and src[i] == quote:
                i += 1
                col_no += 1
            emit("STR", buf, ln, cl)
            continue

        # Numbers
        if c.isdigit():
            start_i = i
            start_col = col_no
            buf = ""
            is_float = False
            dot_count = 0
            while i < L and (src[i].isdigit() or src[i] == "_" or (src[i] == "." and dot_count == 0 and i + 1 < L and src[i+1].isdigit())):
                if src[i] == ".":
                    is_float = True
                    dot_count += 1
                buf += src[i]
                i += 1
                col_no += 1
            # Check exponent
            if i < L and src[i] in ("e", "E"):
                is_float = True
                buf += src[i]
                i += 1
                col_no += 1
                if i < L and src[i] in ("+", "-"):
                    buf += src[i]
                    i += 1
                    col_no += 1
                while i < L and src[i].isdigit():
                    buf += src[i]
                    i += 1
                    col_no += 1
            # Remove underscores
            clean = buf.replace("_", "")
            if is_float:
                emit("FLOAT", clean, ln, start_col)
            else:
                emit("INT", clean, ln, start_col)
            continue

        # Identifiers / keywords
        if c.isalpha() or c == "_":
            start_col = col_no
            buf = ""
            while i < L and (src[i].isalnum() or src[i] == "_"):
                buf += src[i]
                i += 1
                col_no += 1
            if buf in KEYWORDS:
                emit(buf, buf, ln, start_col)
            else:
                emit("NAME", buf, ln, start_col)
            continue

        # Multi-char operators
        matched = False
        for op in MULTI_OPS:
            if src.startswith(op, i):
                emit(op, op, ln, col_no)
                i += len(op)
                col_no += len(op)
                matched = True
                break
        if matched:
            continue

        # Single-char operators
        if c in SINGLE_OPS:
            # bracket depth tracking
            if c in "([{":
                bracket_depth += 1
            elif c in ")]}":
                bracket_depth -= 1
            emit(c, c, ln, col_no)
            i += 1
            col_no += 1
            continue

        # Unknown character
        raise LexerError(f"Unknown character {c!r} at {line_no}:{col_no}")

    # End of source: emit DEDENTs
    while len(indent_stack) > 1:
        indent_stack.pop()
        emit("DEDENT", "", line_no, 1)

    emit("EOF", "", line_no, col_no)
    return tokens