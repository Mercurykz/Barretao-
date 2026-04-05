"""
Gera ícones PNG do Barretão (pizza) para PWA.
Cria: icon-192.png, icon-512.png, icon-maskable-512.png
"""
from PIL import Image, ImageDraw
import os

OUT = os.path.join(os.path.dirname(__file__), "webapp")


def draw_pizza_icon(size: int, maskable: bool = False) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = int(size * 0.08) if maskable else 0

    # Background rounded square
    bg_color = (10, 15, 31, 255)
    r = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=bg_color)

    cx, cy = size // 2, size // 2

    # Safe area for maskable (80% of icon)
    scale = 0.78 if maskable else 0.82
    R = int(size * scale / 2)

    # Crust (outer pizza)
    crust = (214, 134, 61)
    d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=crust)

    # Sauce
    sr = int(R * 0.82)
    sauce = (210, 55, 35)
    d.ellipse([cx - sr, cy - sr, cx + sr, cy + sr], fill=sauce)

    # Cheese blobs (mozzarella)
    cheese = (255, 252, 230)
    blobs = [
        (0.74, 0.82, 0.16),  # top-right
        (0.42, 0.79, 0.14),  # top-left
        (0.79, 0.46, 0.14),  # right
        (0.26, 0.52, 0.13),  # left
        (0.58, 0.62, 0.13),  # center
        (0.44, 1.08, 0.12),  # bottom-right
        (0.68, 1.15, 0.11),  # bottom
    ]
    for bx_frac, by_frac, br_frac in blobs:
        bx = int(cx + R * (bx_frac - 0.74) * 1.4)
        by = int(cy + R * (by_frac - 0.74) * 1.4)
        br = int(R * br_frac)
        # Distribute blobs evenly inside sauce area
    # Simpler direct placement
    blob_specs = [
        (-0.28, -0.28, 0.16),
        ( 0.28, -0.32, 0.15),
        ( 0.40,  0.10, 0.14),
        ( 0.20,  0.38, 0.15),
        (-0.18,  0.40, 0.16),
        (-0.40,  0.05, 0.13),
        ( 0.00,  0.00, 0.11),
    ]
    for dx, dy, rf in blob_specs:
        bx = int(cx + R * dx)
        by = int(cy + R * dy)
        br = int(R * rf)
        d.ellipse([bx - br, by - br, bx + br, by + br], fill=cheese)

    # Pepperoni dots
    pepp = (180, 40, 20)
    pepp_specs = [
        (-0.28, -0.28, 0.07),
        ( 0.28, -0.32, 0.065),
        ( 0.40,  0.10, 0.065),
        ( 0.20,  0.38, 0.07),
        (-0.18,  0.40, 0.07),
        (-0.40,  0.05, 0.06),
    ]
    for dx, dy, rf in pepp_specs:
        bx = int(cx + R * dx)
        by = int(cy + R * dy)
        br = int(R * rf)
        d.ellipse([bx - br, by - br, bx + br, by + br], fill=pepp)

    return img


for size in [192, 512]:
    img = draw_pizza_icon(size, maskable=False)
    path = os.path.join(OUT, f"icon-{size}.png")
    img.save(path, "PNG")
    print(f"✅ {path}")

# Maskable (padded, for Android adaptive icons)
img_m = draw_pizza_icon(512, maskable=True)
path_m = os.path.join(OUT, "icon-maskable-512.png")
img_m.save(path_m, "PNG")
print(f"✅ {path_m}")

print("\nÍcones gerados com sucesso!")
