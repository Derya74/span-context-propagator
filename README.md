# Span Context Propagator

Serializes and deserializes `trace_id`, `span_id`, and trace flags into and
out of W3C Trace Context (`traceparent`) and Baggage header formats.
Standard library only, no third-party dependencies.

## Usage

```python
from span_context_propagator import (
    SpanContext,
    extract_traceparent,
    inject_traceparent,
    extract_baggage,
    inject_baggage,
)

# Incoming request: parse headers into a context.
headers = {
    "traceparent": "00-0af7659818426ccd2c1eaa3b87aeeb76-0286ae46058a4f57-01",
    "baggage": "user_id=42, region=eu",
}
ctx = extract_traceparent(headers)
baggage = extract_baggage(headers)

# Outgoing request: write a context back into headers.
new_ctx = SpanContext(
    trace_id=ctx.trace_id,
    span_id="1234567890abcdef",
    flags=0x01,
)
outgoing: dict = {}
inject_traceparent(outgoing, new_ctx)
inject_baggage(outgoing, {"user_id": "42", "region": "eu"})
```

Headers are plain `dict` objects keyed by the lower-cased header name. If your
HTTP framework uses case-insensitive headers, you are responsible for that
normalization on either side.

## Why this exists

Distributed tracing needs to carry a trace identity across process boundaries.
The W3C Trace Context and Baggage specifications define the wire format, but
not every project wants to pull in OpenTelemetry's full SDK just to read or
write two headers. This library implements exactly those two headers — strict
`traceparent` parsing, loss-free baggage round-tripping — and nothing else.

The trade-off: we do not support unknown `traceparent` versions, do not
carry baggage property metadata, and do not do header name case-insensitive
lookup. Each of those is a real W3C allowance; omitting them keeps the surface
small and the behaviour predictable.

## Edge cases you will hit

- **Duplicate baggage keys.** The W3C spec says the first occurrence of a
  key is authoritative, but real-world multivalued-header joiners produce
  duplicates with last-writer-wins intent. This library picks
  **last-wins** and documents it here rather than silently picking first-wins.
- **Omitted reserved bytes.** Some `traceparent` injectors emit only the
  1-byte flags field (2 hex chars) and omit the trailing reserved byte.
  We accept both 2-char and 4-char flags fields; a non-zero reserved byte is
  rejected as corrupt.
- **Unknown `traceparent` versions.** Rejected, not forwarded. Carrying an
  opaque version blob means we cannot validate the ids, and an unvalidated
  context is worse than no context.
- **Non-ASCII baggage values.** Encoded as UTF-8 byte sequences with
  `%XX` (uppercase hex) per byte, matching RFC 3986. Round-trips safely.

## Public API

| Name | Kind | Purpose |
| --- | --- | --- |
| `SpanContext` | class | Immutable value object: `trace_id`, `span_id`, `flags`. |
| `TRACE_FLAG_SAMPLED` | int | The W3C "sampled" flag bit (`0x01`). |
| `extract_traceparent(headers)` | func | Parse `traceparent` into `SpanContext` or `None`. |
| `inject_traceparent(headers, ctx)` | func | Write `SpanContext` into `headers["traceparent"]`. |
| `extract_baggage(headers)` | func | Parse `baggage` into `dict[str, str]`. |
| `inject_baggage(headers, items)` | func | Write `dict` into `headers["baggage"]`. |

## Running the tests

```
PYTHONPATH=src python -m unittest discover -s tests
```
