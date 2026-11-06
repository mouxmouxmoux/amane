import pytest

from amane.config import ParsingConfig
from amane.parsing import ContentType, FileMarkerRules, Mosaic, parse_file_info


@pytest.mark.parametrize(
    ("name", "mosaic", "subtitle"),
    [
        ("MIDV-123-XYZ.mp4", Mosaic.CRACKED, True),
        ("MIDV-123-xyz-CD1-4K.mp4", Mosaic.CRACKED, True),
        ("MIDV-123-XYZABC.mp4", None, False),
        ("MIDV-123-XYZ1.mp4", None, False),
        ("MIDV-123XYZ.mp4", None, False),
        ("MIDV-123_XYZ.mp4", Mosaic.CRACKED, True),
        ("MIDV-123-U.mp4", None, False),
        ("MIDV-123-UC.mp4", None, False),
        ("MIDV-123-LTX.mp4", None, False),
        ("MIDV-123-L.mp4", Mosaic.LEAKED, False),
        ("MIDV-123-N.mp4", Mosaic.UNCENSORED, False),
        ("MIDV-123-N-L-XYZ.mp4", Mosaic.CRACKED, True),
        ("MIDV-123-N-L.mp4", Mosaic.LEAKED, False),
        ("/流出/MIDV-123-N.mp4", Mosaic.UNCENSORED, False),
        ("/流出/MIDV-123.mp4", Mosaic.LEAKED, False),
        ("/XYZ/MIDV-123.mp4", None, False),
        ("[XYZ]MIDV-123.mp4", Mosaic.CRACKED, True),
    ],
)
def test_configured_markers(name: str, mosaic: Mosaic | None, subtitle: bool) -> None:
    rules = ParsingConfig(
        cracked_suffixes=["XYZ"], leaked_suffixes=["L"], uncensored_suffixes=["N"], subtitle_suffixes=["XYZ"]
    ).to_marker_rules()
    info = parse_file_info(name, marker_rules=rules)
    assert (info.mosaic, info.has_subtitle_in_name) == (mosaic, subtitle)
    assert info.number == "MIDV-123"
    assert info.content_type is ContentType.CENSORED


@pytest.mark.parametrize("text", ["MIDV-123-LTX", "MIDV-123-LTX.mp4"])
def test_text_markers_with_disabled_suffixes(text: str) -> None:
    assert parse_file_info(text=text).mosaic is Mosaic.CRACKED
    disabled = FileMarkerRules(cracked_suffixes=(), subtitle_suffixes=())
    info = parse_file_info(text=text, marker_rules=disabled)
    assert info.number == "MIDV-123"
    assert info.mosaic is None
    assert not info.has_subtitle


@pytest.mark.parametrize("prefix", ["UC", "LTX"])
@pytest.mark.parametrize("pattern", ["{}.mp4", "[{}].mp4", "foo {}.mp4", "foo-{}.mp4", "【{}】.mp4"])
def test_number_prefix_is_not_marker(prefix: str, pattern: str) -> None:
    number = f"{prefix}-123"
    info = parse_file_info(pattern.format(number))
    assert info.number == number
    assert info.mosaic is None
    assert not info.has_subtitle_in_name
    marked = parse_file_info(pattern.format(number + "-UC"))
    assert marked.number == number
    assert marked.mosaic is Mosaic.CRACKED
    assert marked.has_subtitle_in_name
