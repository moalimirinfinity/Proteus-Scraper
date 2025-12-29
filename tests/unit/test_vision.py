from scraper.vision import detect_ocr_signal


def test_detect_ocr_signal() -> None:
    assert detect_ocr_signal("Please verify you are human") == "vision_ocr_block"
    assert detect_ocr_signal("Welcome to the site") is None
