
import numpy as np


class SaveImageError(Exception):
    pass


class ImageAscii:

    def __init__(self, image):
        self.image = image

    def save(self, path, format=None):
        img_arr = np.array(self.image)
        block = np.array(["  ", "██"])
        mapped = block[img_arr.astype(int)]
        ascii_qr = "\n".join("".join(row) for row in mapped)
        try:
            with open(path, "w", encoding="utf8") as f:
                f.write(ascii_qr)
        except Exception as e:
            raise SaveImageError("Error saving ascii image, %s", e)
