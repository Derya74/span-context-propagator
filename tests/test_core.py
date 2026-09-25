import unittest

from span_context_propagator import (
    SpanContext,
    TRACE_FLAG_SAMPLED,
    extract_traceparent,
    inject_traceparent,
    extract_baggage,
    inject_baggage,
)
from span_context_propagator.core import SpanContextError


class TestSpanContextConstruction(unittest.TestCase):
    def test_valid_context_round_trips(self):
        ctx = SpanContext(
            trace_id="0af7659818426ccd2c1eaa3b87aeeb76",
            span_id="0286ae46058a4f57",
            flags=0x01,
        )
        self.assertEqual(ctx.trace_id, "0af7659818426ccd2c1eaa3b87aeeb76")
        self.assertEqual(ctx.span_id, "0286ae46058a4f57")
        self.assertEqual(ctx.flags, 1)
        self.assertTrue(ctx.sampled)

    def test_uppercase_hex_normalised_to_lower(self):
        ctx = SpanContext(
            trace_id="0AF7659818426CCD2C1EAA3B87AEEB76",
            span_id="0286AE46058A4F57",
            flags=0x01,
        )
        self.assertEqual(ctx.trace_id, "0af7659818426ccd2c1eaa3b87aeeb76")
        self.assertEqual(ctx.span_id, "0286ae46058a4f57")

    def test_zero_trace_id_rejected(self):
        with self.assertRaises(ValueError):
            SpanContext(trace_id="0" * 32, span_id="0286ae46058a4f57", flags=0)

    def test_zero_span_id_rejected(self):
        with self.assertRaises(ValueError):
            SpanContext(
                trace_id="0af7659818426ccd2c1eaa3b87aeeb76",
                span_id="0" * 16,
                flags=0,
            )

    def test_wrong_length_ids_rejected(self):
        with self.assertRaises(ValueError):
            SpanContext(trace_id="abc", span_id="0286ae46058a4f57", flags=0)
        with self.assertRaises(ValueError):
            SpanContext(
                trace_id="0af7659818426ccd2c1eaa3b87aeeb76",
                span_id="abc",
                flags=0,
            )

    def test_non_hex_ids_rejected(self):
        with self.assertRaises(ValueError):
            SpanContext(
                trace_id="zaf7659818426ccd2c1eaa3b87aeeb76",
                span_id="0286ae46058a4f57",
                flags=0,
            )

    def test_flags_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            SpanContext(
                trace_id="0af7659818426ccd2c1eaa3b87aeeb76",
                span_id="0286ae46058a4f57",
                flags=0x100,
            )

    def test_flags_bool_rejected(self):
        # bool is a subclass of int; we forbid it so callers don't accidentally
        # inject a literal boolean into a byte field.
        with self.assertRaises(TypeError):
            SpanContext(
                trace_id="0af7659818426ccd2c1eaa3b87aeeb76",
                span_id="0286ae46058a4f57",
                flags=True,
            )

    def test_immutable(self):
        ctx = SpanContext(
            trace_id="0af7659818426ccd2c1eaa3b87aeeb76",
            span_id="0286ae46058a4f57",
            flags=0x01,
        )
        with self.assertRaises(Exception):
            ctx.trace_id = "1" * 32  # type: ignore[misc]

    def test_sampled_property_reflects_flag_bit(self):
        sampled = SpanContext(
            trace_id="0af7659818426ccd2c1eaa3b87aeeb76",
            span_id="0286ae46058a4f57",
            flags=TRACE_FLAG_SAMPLED,
        )
        not_sampled = SpanContext(
            trace_id="0af7659818426ccd2c1eaa3b87aeeb76",
            span_id="0286ae46058a4f57",
            flags=0,
        )
        self.assertTrue(sampled.sampled)
        self.assertFalse(not_sampled.sampled)

    def test_higher_flag_bits_preserved(self):
        # Only bit 0 is defined by W3C, but higher bits must round-trip so
        # future flag definitions don't break older propagators.
        ctx = SpanContext(
            trace_id="0af7659818426ccd2c1eaa3b87aeeb76",
            span_id="0286ae46058a4f57",
            flags=0x80 | TRACE_FLAG_SAMPLED,
        )
        self.assertTrue(ctx.sampled)
        self.assertEqual(ctx.to_traceparent().split("-")[3], "81")


class TestTraceparentRoundTrip(unittest.TestCase):
    def test_to_from_traceparent_round_trip(self):
        ctx = SpanContext(
            trace_id="0af7659818426ccd2c1eaa3b87aeeb76",
            span_id="0286ae46058a4f57",
            flags=0x01,
        )
        header = ctx.to_traceparent()
        self.assertEqual(
            header,
            "00-0af7659818426ccd2c1eaa3b87aeeb76-0286ae46058a4f57-01",
        )
        self.assertEqual(SpanContext.from_traceparent(header), ctx)

    def test_from_traceparent_strips_surrounding_whitespace(self):
        ctx = SpanContext.from_traceparent(
            "  00-0af7659818426ccd2c1eaa3b87aeeb76-0286ae46058a4f57-01  "
        )
        self.assertEqual(ctx.span_id, "0286ae46058a4f57")

    def test_from_traceparent_accepts_uppercase(self):
        ctx = SpanContext.from_traceparent(
            "00-0AF7659818426CCD2C1EAA3B87AEEB76-0286AE46058A4F57-01"
        )
        self.assertEqual(ctx.trace_id, "0af7659818426ccd2c1eaa3b87aeeb76")
        self.assertEqual(ctx.span_id, "0286ae46058a4f57")

    def test_from_traceparent_rejects_unknown_version(self):
        with self.assertRaises(SpanContextError):
            SpanContext.from_traceparent(
                "01-0af7659818426ccd2c1eaa3b87aeeb76-0286ae46058a4f57-01"
            )

    def test_from_traceparent_rejects_wrong_field_count(self):
        with self.assertRaises(SpanContextError):
            SpanContext.from_traceparent(
                "00-0af7659818426ccd2c1eaa3b87aeeb76-0286ae46058a4f57"
            )
        with self.assertRaises(SpanContextError):
            SpanContext.from_traceparent(
                "00-0af7659818426ccd2c1eaa3b87aeeb76-0286ae46058a4f57-01-extra"
            )

    def test_from_traceparent_rejects_all_zero_ids(self):
        with self.assertRaises(SpanContextError):
            SpanContext.from_traceparent(
                "00-00000000000000000000000000000000-0286ae46058a4f57-01"
            )
        with self.assertRaises(SpanContextError):
            SpanContext.from_traceparent(
                "00-0af7659818426ccd2c1eaa3b87aeeb76-0000000000000000-01"
            )

    def test_from_traceparent_rejects_bad_flags_length(self):
        with self.assertRaises(SpanContextError):
            SpanContext.from_traceparent(
                "00-0af7659818426ccd2c1eaa3b87aeeb76-0286ae46058a4f57-1"
            )
        with self.assertRaises(SpanContextError):
            SpanContext.from_traceparent(
                "00-0af7659818426ccd2c1eaa3b87aeeb76-0286ae46058a4f57-010203"
            )

    def test_from_traceparent_rejects_non_zero_reserved_byte(self):
        # 4-char flags where the high byte is non-zero is corrupt per W3C.
        with self.assertRaises(SpanContextError):
            SpanContext.from_traceparent(
                "00-0af7659818426ccd2c1eaa3b87aeeb76-0286ae46058a4f57-0101"
            )

    def test_from_traceparent_accepts_omitted_reserved_bytes(self):
        # Some injectors emit only the 1 flags byte (2 hex chars). We accept it
        # and treat the missing reserved byte as zero.
        ctx = SpanContext.from_traceparent(
            "00-0af7659818426ccd2c1eaa3b87aeeb76-0286ae46058a4f57-01"
        )
        self.assertEqual(ctx.flags, 1)

    def test_from_traceparent_rejects_empty(self):
        with self.assertRaises(SpanContextError):
            SpanContext.from_traceparent("")

    def test_from_traceparent_rejects_non_str(self):
        with self.assertRaises(TypeError):
            SpanContext.from_traceparent(b"00-abc")  # type: ignore[arg-type]


class TestExtractInjectTraceparent(unittest.TestCase):
    def test_extract_returns_none_when_absent(self):
        self.assertIsNone(extract_traceparent({}))
        self.assertIsNone(extract_traceparent({"traceparent": ""}))

    def test_extract_returns_context_when_present(self):
        headers = {
            "traceparent": "00-0af7659818426ccd2c1eaa3b87aeeb76-0286ae46058a4f57-01"
        }
        ctx = extract_traceparent(headers)
        self.assertIsInstance(ctx, SpanContext)
        self.assertEqual(ctx.trace_id, "0af7659818426ccd2c1eaa3b87aeeb76")
        self.assertTrue(ctx.sampled)

    def test_extract_raises_on_malformed(self):
        with self.assertRaises(SpanContextError):
            extract_traceparent({"traceparent": "garbage"})

    def test_inject_writes_header(self):
        headers: dict = {}
        ctx = SpanContext(
            trace_id="0af7659818426ccd2c1eaa3b87aeeb76",
            span_id="0286ae46058a4f57",
            flags=0x01,
        )
        inject_traceparent(headers, ctx)
        self.assertEqual(
            headers["traceparent"],
            "00-0af7659818426ccd2c1eaa3b87aeeb76-0286ae46058a4f57-01",
        )

    def test_inject_overwrites_existing(self):
        headers = {"traceparent": "stale"}
        ctx = SpanContext(
            trace_id="0af7659818426ccd2c1eaa3b87aeeb76",
            span_id="0286ae46058a4f57",
            flags=0x00,
        )
        inject_traceparent(headers, ctx)
        self.assertTrue(headers["traceparent"].startswith("00-"))

    def test_inject_rejects_non_context(self):
        with self.assertRaises(TypeError):
            inject_traceparent({}, "not-a-context")  # type: ignore[arg-type]

    def test_inject_rejects_non_dict_headers(self):
        ctx = SpanContext(
            trace_id="0af7659818426ccd2c1eaa3b87aeeb76",
            span_id="0286ae46058a4f57",
            flags=0x01,
        )
        with self.assertRaises(TypeError):
            inject_traceparent([], ctx)  # type: ignore[arg-type]

    def test_full_round_trip_through_headers(self):
        original = SpanContext(
            trace_id="0af7659818426ccd2c1eaa3b87aeeb76",
            span_id="0286ae46058a4f57",
            flags=0x01,
        )
        headers: dict = {}
        inject_traceparent(headers, original)
        extracted = extract_traceparent(headers)
        self.assertIsNotNone(extracted)
        assert extracted is not None
        self.assertEqual(extracted, original)


class TestBaggage(unittest.TestCase):
    def test_extract_empty_returns_empty_dict(self):
        self.assertEqual(extract_baggage({}), {})
        self.assertEqual(extract_baggage({"baggage": ""}), {})

    def test_extract_single_pair(self):
        self.assertEqual(
            extract_baggage({"baggage": "key=value"}),
            {"key": "value"},
        )

    def test_extract_multiple_pairs(self):
        self.assertEqual(
            extract_baggage({"baggage": "a=1, b=2, c=3"}),
            {"a": "1", "b": "2", "c": "3"},
        )

    def test_extract_strips_whitespace(self):
        self.assertEqual(
            extract_baggage({"baggage": "  a = 1 ,  b = 2  "}),
            {"a": "1", "b": "2"},
        )

    def test_extract_drops_properties(self):
        # Per-item properties (after ';') are metadata, not user-visible data.
        self.assertEqual(
            extract_baggage({"baggage": "a=1;prop=x, b=2;prop=y"}),
            {"a": "1", "b": "2"},
        )

    def test_extract_skips_malformed_entries(self):
        # Entries without '=' are skipped, not fatal.
        self.assertEqual(
            extract_baggage({"baggage": "a=1, broken, b=2"}),
            {"a": "1", "b": "2"},
        )

    def test_extract_skips_empty_key(self):
        self.assertEqual(
            extract_baggage({"baggage": "=value, a=1"}),
            {"a": "1"},
        )

    def test_extract_tolerates_empty_chunks(self):
        # Double commas, trailing commas.
        self.assertEqual(
            extract_baggage({"baggage": "a=1,, b=2,"}),
            {"a": "1", "b": "2"},
        )

    def test_extract_last_wins_for_duplicate_keys(self):
        # Documented behaviour: duplicates overwrite, last wins.
        self.assertEqual(
            extract_baggage({"baggage": "a=1, a=2, a=3"}),
            {"a": "3"},
        )

    def test_extract_decodes_percent_encoded_values(self):
        self.assertEqual(
            extract_baggage({"baggage": "key=hello%20world"}),
            {"key": "hello world"},
        )

    def test_extract_decodes_percent_encoded_keys(self):
        self.assertEqual(
            extract_baggage({"baggage": "user%20id=42"}),
            {"user id": "42"},
        )

    def test_inject_single_pair(self):
        headers: dict = {}
        inject_baggage(headers, {"key": "value"})
        self.assertEqual(headers["baggage"], "key=value")

    def test_inject_multiple_pairs_preserves_insertion_order(self):
        headers: dict = {}
        inject_baggage(headers, {"a": "1", "b": "2", "c": "3"})
        self.assertEqual(headers["baggage"], "a=1, b=2, c=3")

    def test_inject_empty_mapping_produces_empty_header(self):
        headers: dict = {}
        inject_baggage(headers, {})
        self.assertEqual(headers["baggage"], "")

    def test_inject_percent_encodes_unsafe_chars(self):
        headers: dict = {}
        inject_baggage(headers, {"user id": "hello world"})
        self.assertEqual(headers["baggage"], "user%20id=hello%20world")

    def test_inject_keeps_safe_chars_verbatim(self):
        headers: dict = {}
        inject_baggage(headers, {"a-b.c_d": "value/123"})
        self.assertEqual(headers["baggage"], "a-b.c_d=value/123")

    def test_inject_encodes_non_ascii_as_utf8_percent(self):
        headers: dict = {}
        inject_baggage(headers, {"city": "Zürich"})
        # ü = 0xC3 0xBC in UTF-8.
        self.assertEqual(headers["baggage"], "city=Z%C3%BCrich")

    def test_baggage_round_trip_safe_chars(self):
        original = {"a": "1", "b": "2"}
        headers: dict = {}
        inject_baggage(headers, original)
        self.assertEqual(extract_baggage(headers), original)

    def test_baggage_round_trip_unsafe_chars(self):
        original = {"user id": "hello world"}
        headers: dict = {}
        inject_baggage(headers, original)
        self.assertEqual(extract_baggage(headers), original)

    def test_baggage_round_trip_non_ascii(self):
        original = {"city": "Zürich"}
        headers: dict = {}
        inject_baggage(headers, original)
        self.assertEqual(extract_baggage(headers), original)

    def test_inject_rejects_non_dict_headers(self):
        with self.assertRaises(TypeError):
            inject_baggage([], {"a": "1"})  # type: ignore[arg-type]

    def test_inject_rejects_non_string_values(self):
        with self.assertRaises(TypeError):
            inject_baggage({}, {"a": 1})  # type: ignore[dict-item]


if __name__ == "__main__":
    unittest.main()
