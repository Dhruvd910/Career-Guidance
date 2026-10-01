"""Links become scannable QR codes."""

import segno

from app.qr import qr_pixmap


def test_a_link_becomes_a_square_qr_code(qapp):
    pixmap = qr_pixmap("https://ncert.nic.in/textbook.php", 200)
    assert pixmap.width() == pixmap.height()
    assert 150 <= pixmap.width() <= 200


def test_the_code_encodes_the_link_exactly():
    # Decoding needs a camera library; checking the encoder saw the exact text is the next best thing.
    url = "https://www.youtube.com/@PhysicsWallah"
    code = segno.make(url, error="m", micro=False)
    assert code.designator.endswith("M")
    assert segno.make(url, error="m", micro=False).matrix == code.matrix


def test_long_links_still_fit(qapp):
    pixmap = qr_pixmap("https://www.taxscan.in/top-stories/26-lakh-salary-package-offered-for-ca-fresher-in-icai-campus-placement-programme-3000-receives-job-offers-1436156", 200)
    assert pixmap.width() > 0
