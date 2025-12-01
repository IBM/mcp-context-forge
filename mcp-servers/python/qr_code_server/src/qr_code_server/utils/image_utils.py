
import numpy as np
import qrcode


class SaveImageError(Exception):
    pass


class ImageAscii(qrcode.image.base.BaseImage):

    def __init__(self, border, width, box_size, qrcode_modules=None, **kwargs):
        self.border = border
        self.width = width
        self.box_size = box_size
        self.image = qrcode_modules

    def to_string(self) -> str:
        img_arr = np.array(self.image)
        block = np.array(["  ", "██"], dtype=str)
        mapped = block[img_arr.astype(int)]
        return "\n".join("".join(row) for row in mapped)

    def save(self, path):
        ascii_qr = self.to_string()
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(ascii_qr)
        except Exception as e:
            raise SaveImageError(f"Error saving ASCII image: {e}") from e
