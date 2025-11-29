from pathlib import Path
from tempfile import TemporaryDirectory

from qr_code_server.tools.generator import QRGenerationRequest, create_qr


def test_create_qr_saves_file():
    with TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "qr.png"

        req = QRGenerationRequest(
            data="https://test.com",
            save_path=str(file_path),
        )
        create_qr(req)

        # Assert the file exists
        assert file_path.exists()
        assert file_path.is_file()

