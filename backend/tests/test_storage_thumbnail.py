import base64
from io import BytesIO

from PIL import Image

from storage import compact_image_data_url


def _image_data_url(width=640, height=480):
    image = Image.new("RGB", (width, height), (30, 120, 210))
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def test_compact_image_data_url_creates_small_webp_thumbnail():
    source = _image_data_url()
    compact = compact_image_data_url(source, max_size=128, quality=50)

    assert compact.startswith("data:image/webp;base64,")
    assert len(compact) < len(source)

    decoded = base64.b64decode(compact.split(",", 1)[1])
    with Image.open(BytesIO(decoded)) as thumbnail:
        assert thumbnail.format == "WEBP"
        assert max(thumbnail.size) <= 128


def test_compact_image_data_url_preserves_remote_urls_and_invalid_payloads():
    url = "https://images.example.test/face.webp"
    assert compact_image_data_url(url) == url
    assert compact_image_data_url("not-base64") == "not-base64"
