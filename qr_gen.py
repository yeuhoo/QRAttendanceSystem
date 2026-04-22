import os
import qrcode


def generate_qr_code(data: str, filepath: str) -> None:
    """Generate a QR code PNG encoding `data` and save it to `filepath`."""
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(filepath)
