from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def fake_pdf_rendering(request):
    """Real PDFs are slow to generate: tests get a fake one unless marked real_pdf."""
    if request.node.get_closest_marker("real_pdf"):
        yield None
        return
    with mock.patch("weasyprint.HTML") as html:
        html.return_value.write_pdf.return_value = b"%PDF-1.7 fake test pdf"
        yield html
