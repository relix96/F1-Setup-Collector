from dataclasses import dataclass

import pytest


@dataclass
class FakeResponse:
    text: str


@pytest.fixture
def setup_html() -> str:
    return """
    <main>
      <a data-setup-id="42"
         data-circuit="Monza"
         data-car="Ferrari"
         href="https://example.test/setups/42">Setup</a>
      <a href="https://example.test/about">Not a setup</a>
    </main>
    """
