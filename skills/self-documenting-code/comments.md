# Comments

The rule is in SKILL.md. This is how to adjudicate one specific line.

## The two tests

**Body line - the knower test.** Someone who knows the external thing (the language, the library, the algorithm) and has never seen this repo would write the same line. If only you could have written it, it describes your decision rather than the world, and it is an alarm. Apply per clause: "standard sliding window" passes, "except we skip step 3 because our input is pre-sorted" is a decision whose cause happens to be inherited.

**Interface docstring - the caller test.** Name and types are exhausted, and deleting the line would force a caller into the body to call safely. `Optional[int]` already carries "may be None", `timeout_seconds` already carries units, `sorted_rows` already carries ordering. Most contract docstrings die here.

Reviewers falsify constructively - look the algorithm up, or move the contract into the name or a type. If that works, the line goes.

## Answering the alarm

```python
# WRONG - justification as prose
def _error_row(exc):
    """SyntaxError exposes .lineno; TokenError only carries it positionally
    in .args, which is not a guaranteed shape - validated defensively so the
    caller fails open rather than resyncing to a wrong line."""

# ALSO WRONG - same justification, smuggled into the name
def _row_from_undocumented_token_error_args(exc): ...

# RIGHT - name carries contract, one inherited fact stays at the line
def _reported_row(exc):
    if isinstance(exc, SyntaxError):
        return exc.lineno
    return exc.args[1][0]  # TokenError: row is positional in .args, undocumented
```

The middle panel is the trap: "make the name carry it" is not licence to pack justification into an identifier. A name states the contract, never the reasoning.

## Test prose

```python
# WRONG
def test_prefix(self):
    """An r-prefixed docstring token should still be detected as triple-quoted,
    because the prefix has to be stripped before the quote check."""

# RIGHT
def test_r_prefixed_docstring_is_detected_as_triple_quoted(self): ...
```
