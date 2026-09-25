"""Span Context Propagator.

Serializes and deserializes trace_id, span_id, and flags into and from W3C
Trace Context (``traceparent``) and Baggage header formats.

Public surface:
    SpanContext        -- immutable value object for a span context
    TRACE_FLAG_SAMPLED -- the W3C "sampled" flag bit
    extract_traceparent(headers)   -- parse a traceparent header into SpanContext
    inject_traceparent(headers, ctx) -- write a SpanContext into a traceparent header
    extract_baggage(headers)        -- parse a Baggage header into a dict
    inject_baggage(headers, items)  -- write a dict into a Baggage header

Headers are read from / written into plain ``dict`` objects keyed by the
lower-cased header name. The caller is responsible for any case-insensitive
normalization required by the surrounding HTTP framework.
"""

from .core import (
    SpanContext,
    TRACE_FLAG_SAMPLED,
    extract_traceparent,
    inject_traceparent,
    extract_baggage,
    inject_baggage,
)

__all__ = [
    "SpanContext",
    "TRACE_FLAG_SAMPLED",
    "extract_traceparent",
    "inject_traceparent",
    "extract_baggage",
    "inject_baggage",
]
