"""warm_model.py's own entry point — the exact thing `docker build` and
`make warm-model` run. Fast here because Layer 2's fixture already cached the
model; this just proves `main()` itself doesn't raise.
"""

import pytest

from pipeline.warm_model import main

pytestmark = pytest.mark.slow


def test_warm_model_main_does_not_raise(capsys):
    main()
    out = capsys.readouterr().out
    assert "done." in out
