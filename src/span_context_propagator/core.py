"""Core implementation for span context propagation.

This module deals with two W3C specifications:

* Trace Context (``traceparent``): carries ``trace_id``, ``span_id`` and a set
  of 8 trace flags packed into a hex byte.
* Baggage: carries an opaque list of key/value pairs.

The format details that actually bite you:

* ``traceparent`` is versioned. Version ``00`` is the only one in widespread
  use; the spec says a propagator MAY forward unknown versions unchanged, but
  for a focused library that is out of scope. We reject unknown versions so
  that a malformed header does not silently produce a bogus context.
* The two trailing bytes of a v0 ``traceparent`` are reserved and MUST be
  zero. Some injectors omit them; we tolerate omission (treat as zero) but
  reject a non-zero value because that indicates a genuinely corrupt header.
* ``trace_id`` and ``span_id`` must not be all-zero. An all-zero id is the
  W3C sentinel for "no valid context"; accepting it would let a bad header
  masquerade as a real trace.
* Baggage values may be percent-encoded (``%xx``). Keys and values may also
  contain tokens verbatim. We preserve raw bytes by storing decoded strings;
  characters outside the ASCII range are preserved as their original form.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Tuple
from urllib.parse import unquote


# The single trace flag defined by W3C Trace Context level 1: "sampled".
# Bit 0 of the 8-bit flags field. Higher bits are reserved for future use
# and are carried through untouched on both inject and extract.
TRACE_FLAG_SAMPLED: int = 0x01

_TRACEPARENT_HEADER = "traceparent"
_BAGGAGE_HEADER = "baggage"


class SpanContextError(ValueError):
    """Raised when a traceparent header cannot be parsed.

    A dedicated exception (rather than bare ``ValueError``) lets callers
    distinguish propagation failures from other value errors in their stack.
    """


@dataclass(frozen=True)
class SpanContext:
    """An immutable W3C Trace Context span identity.

    Attributes:
        trace_id: 32 lowercase hex chars (16 bytes), never all-zero.
        span_id:  16 lowercase hex chars (8 bytes), never all-zero.
        flags:    8-bit trace flags (only bit 0, ``TRACE_FLAG_SAMPLED``, is
                  defined by W3C; higher bits are preserved verbatim).
    """

    trace_id: str
    span_id: str
    flags: int = 0

    def __post_init__(self) -> None:
        # __post_init__ runs after dataclass assignment; with frozen=True we
        # must bypass the field's __set__ via object.__setattr__ to validate
        # and normalise inputs in one place.
        if not isinstance(self.trace_id, str) or not isinstance(self.span_id, str):
            raise TypeError("trace_id and span_id must be str")
        if not _is_hex(self.trace_id, 32):
            raise ValueError("trace_id must be 32 lowercase hex chars")
        if not _is_hex(self.span_id, 16):
            raise ValueError("span_id must be 16 lowercase hex chars")
        if self.trace_id == "0" * 32:
            raise ValueError("trace_id must not be all-zero")
        if self.span_id == "0" * 16:
            raise ValueError("span_id must not be all-zero")
        if not isinstance(self.flags, int) or isinstance(self.flags, bool):
            raise TypeError("flags must be int")
        if not 0 <= self.flags <= 0xFF:
            raise ValueError("flags must fit in one byte (0..255)")

        # Normalise hex to lowercase so equality and serialization are stable.
        object.__setattr__(self, "trace_id", self.trace_id.lower())
        object.__setattr__(self, "span_id", self.span_id.lower())

    @property
    def sampled(self) -> bool:
        """True iff the W3C ``sampled`` flag bit is set."""
        return bool(self.flags & TRACE_FLAG_SAMPLED)

    def to_traceparent(self) -> str:
        """Serialize this context into a W3C ``traceparent`` header value."""
        return (
            "00-"
            f"{self.trace_id}-"
            f"{self.span_id}-"
            f"{self.flags:02x}"
        )

    @classmethod
    def from_traceparent(cls, value: str) -> "SpanContext":
        """Parse a W3C ``traceparent`` header value.

        Strict parser: requires version 00, well-formed hex ids, non-zero ids,
        and zero reserved bytes (if present). Whitespace surrounding the value
        is tolerated; internal structure is not.
        """
        if not isinstance(value, str):
            raise TypeError("traceparent value must be str")
        value = value.strip()
        if not value:
            raise SpanContextError("empty traceparent")

        parts = value.split("-")
        if len(parts) != 4:
            raise SpanContextError(
                f"traceparent must have 4 dash-separated fields, got {len(parts)}"
            )
        version, trace_id, span_id, flags_part = parts

        if version.lower() != "00":
            # W3C: a propagator may forward unknown versions, but we deliberately
            # do not. Carrying an opaque blob means we cannot validate the ids,
            # and an unvalidated context is worse than no context.
            raise SpanContextError(f"unsupported traceparent version: {version!r}")

        if not _is_hex(trace_id, 32):
            raise SpanContextError("trace_id must be 32 hex chars")
        if not _is_hex(span_id, 16):
            raise SpanContextError("span_id must be 16 hex chars")
        if trace_id.lower() == "0" * 32:
            raise SpanContextError("trace_id must not be all-zero")
        if span_id.lower() == "0" * 16:
            raise SpanContextError("span_id must not be all-zero")

        # flags_part is 2 hex chars; some injectors omit the 2 reserved bytes
        # that follow. Tolerate omission, reject non-zero reserved bytes.
        if len(flags_part) not in (2, 4):
            raise SpanContextError(
                f"flags field must be 2 or 4 hex chars, got {len(flags_part)}"
            )
        if not _is_hex(flags_part, len(flags_part)):
            raise SpanContextError("flags field is not hex")
        flags = int(flags_part, 16)
        if len(flags_part) == 4 and (flags & 0xFF00) != 0:
            raise SpanContextError("reserved trace flags bytes must be zero")
        flags &= 0xFF

        return cls(trace_id=trace_id, span_id=span_id, flags=flags)


def extract_traceparent(headers: Mapping[str, str]) -> Optional[SpanContext]:
    """Extract a ``SpanContext`` from a headers mapping.

    Returns ``None`` when the header is absent or empty. Raises
    ``SpanContextError`` when the header is present but malformed — callers
    can distinguish "no incoming context" from "corrupt incoming context".
    """
    raw = headers.get(_TRACEPARENT_HEADER)
    if raw is None or raw == "":
        return None
    return SpanContext.from_traceparent(raw)


def inject_traceparent(headers: Dict[str, str], ctx: SpanContext) -> None:
    """Write ``ctx`` into ``headers`` under the ``traceparent`` key.

    Overwrites any existing value. Mutates ``headers`` in place and returns
    nothing, mirroring how OpenTelemetry style injectors behave.
    """
    if not isinstance(ctx, SpanContext):
        raise TypeError("ctx must be a SpanContext")
    if not isinstance(headers, dict):
        raise TypeError("headers must be a dict")
    headers[_TRACEPARENT_HEADER] = ctx.to_traceparent()


def extract_baggage(headers: Mapping[str, str]) -> Dict[str, str]:
    """Parse a W3C Baggage header into a dict.

    Baggage is a comma-separated list of ``key=value`` pairs, each optionally
    followed by ``;prop=value`` metadata. The metadata is discarded: this
    library carries only the user-visible keys and values.

    Duplicate keys: later entries win (W3C says the first occurrence of a key
    is authoritative, but every real-world multivalued-header joiner produces
    duplicates with the last-writer-wins intent). We pick last-wins and say so
    in the README rather than silently picking first-wins.

    Empty header -> empty dict. Percent-encoded values are decoded.
    """
    raw = headers.get(_BAGGAGE_HEADER)
    if raw is None or raw == "":
        return {}
    return _parse_baggage(raw)


def inject_baggage(headers: Dict[str, str], items: Mapping[str, str]) -> None:
    """Serialize ``items`` into a Baggage header value.

    Keys and values are emitted verbatim when they contain only baggage-safe
    characters; otherwise they are percent-encoded. This keeps the common case
    readable while guaranteeing round-trip safety.
    """
    if not isinstance(headers, dict):
        raise TypeError("headers must be a dict")
    if not isinstance(items, Mapping):
        raise TypeError("items must be a Mapping")
    pairs: List[str] = []
    for key, value in items.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise TypeError("baggage keys and values must be str")
        pairs.append(f"{_encode_baggage_token(key)}={_encode_baggage_token(value)}")
    headers[_BAGGAGE_HEADER] = ", ".join(pairs)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_hex(s: str, length: int) -> bool:
    """True iff ``s`` is exactly ``length`` lowercase-or-uppercase hex chars.

    ``str.isalnum`` would also accept non-ASCII digits; we need strict ASCII
    hex because W3C parsers are byte-oriented.
    """
    if len(s) != length:
        return False
    for c in s:
        if not ("0" <= c <= "9" or "a" <= c <= "f" or "A" <= c <= "F"):
            return False
    return True


def _parse_baggage(raw: str) -> Dict[str, str]:
    """Parse a Baggage header value into an ordered dict.

    The grammar is::

        baggage    = list *("," OWS list)
        list       = key "=" value *(";" OWS prop)
        key        = token
        value      = token / percent-encoded

    We split on commas, then on the first ``=`` per item, then drop anything
    after the first ``;`` (property metadata). Percent-encoded sequences in
    keys and values are decoded via ``urllib.parse.unquote``.
    """
    result: Dict[str, str] = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            # Trailing/leading/double commas produce empty chunks. Skip them
            # rather than raising — W3C tolerates OWS around list separators.
            continue
        # Strip per-item properties (";key=value").
        item = chunk.split(";", 1)[0].strip()
        if "=" not in item:
            # Malformed entry: no key/value separator. Skip it. We do not raise
            # because the W3C baggage spec says receivers should tolerate
            # individual bad entries rather than fail the whole header.
            continue
        key, value = item.split("=", 1)
        key = unquote(key.strip())
        value = unquote(value.strip())
        if not key:
            continue
        # Last-wins for duplicate keys (see extract_baggage docstring).
        result[key] = value
    return result


# Baggage keys/values are restricted to a subset of token chars plus a few
# separators. Anything outside this set gets percent-encoded on inject.
_BAGGAGE_SAFE = set(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "-._!#$&'()*+/:?@"
)


def _encode_baggage_token(token: str) -> str:
    """Percent-encode a baggage key or value where needed.

    We percent-encode anything outside the baggage-safe set. For ASCII bytes
    we emit ``%XX`` (uppercase hex, matching RFC 3986). Non-ASCII chars are
    encoded as their UTF-8 byte sequence, each byte becoming ``%XX``.
    """
    out: List[str] = []
    for ch in token:
        if ch in _BAGGAGE_SAFE:
            out.append(ch)
        else:
            for b in ch.encode("utf-8"):
                out.append(f"%{b:02X}")
    return "".join(out)
