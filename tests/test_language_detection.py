from mlx_ui.language_detection import detect_parakeet_transcript_language


def test_detect_parakeet_transcript_language_returns_supported_language() -> None:
    language, confidence = detect_parakeet_transcript_language(
        "Здравствуйте, сегодня мы обсуждаем условия договора и следующие шаги."
    )

    assert language == "ru"
    assert confidence is not None and 0.8 <= confidence <= 1.0


def test_detect_parakeet_transcript_language_rejects_ambiguous_short_text() -> None:
    assert detect_parakeet_transcript_language("No") == (None, None)
