from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_index_script_partial_loads_external_modules() -> None:
    script_partial = (
        ROOT_DIR / "mlx_ui" / "templates" / "partials" / "index" / "script.html"
    )
    source = script_partial.read_text(encoding="utf-8")

    assert 'document.documentElement.classList.add("js")' in source
    assert 'src="/static/js/index/main.js"' in source
    assert "(function" not in source

    static_dir = ROOT_DIR / "mlx_ui" / "static" / "js" / "index"
    expected_files = [
        "core.js",
        "utils.js",
        "time.js",
        "tabs.js",
        "history_view.js",
        "render_jobs.js",
        "toasts.js",
        "modals.js",
        "worker_card.js",
        "state.js",
        "uploads.js",
        "settings.js",
        "queue_actions.js",
        "history_actions.js",
        "storage_actions.js",
        "main.js",
    ]
    for name in expected_files:
        assert (static_dir / name).is_file()
