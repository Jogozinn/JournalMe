from app.config import Settings


def test_cors_origins_are_trimmed_deduplicated_and_trailing_slashes_removed():
    settings = Settings(
        cors_origins=(
            " https://journalme-beige.vercel.app/,"
            "http://localhost:3070/,"
            "https://journalme-beige.vercel.app "
        )
    )
    assert settings.cors_origin_list == [
        "https://journalme-beige.vercel.app",
        "http://localhost:3070",
    ]
