"""生成「Radio」App 图标（收音机造型）。

先在 1024 画布上画，再按密度缩放到各 mipmap 尺寸。
"""
import os
from PIL import Image, ImageDraw

OUT = r"C:\Users\小米\Documents\deepseek-harness\radio\src\SmsForwarder\app\src\main\res"
PREVIEW = r"C:\Users\小米\Documents\deepseek-harness\radio\icon_preview.png"

S = 1024
BG_TOP = (27, 58, 107)
BG_BOT = (46, 111, 183)
CREAM = (246, 241, 228)
DARK = (42, 59, 76)
ACCENT = (228, 87, 46)
AMBER = (255, 180, 59)


def bg_gradient(size):
    img = Image.new("RGBA", (size, size))
    d = ImageDraw.Draw(img)
    for y in range(size):
        t = y / (size - 1)
        c = tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3)) + (255,)
        d.line([(0, y), (size, y)], fill=c)
    return img


def draw_icon(size=S):
    # 圆角方形底（全幅，之后按需要裁圆角）
    base = bg_gradient(size)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=255)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.paste(base, (0, 0), mask)
    d = ImageDraw.Draw(img)

    k = size / 1024.0

    def sc(*v):
        return [x * k for x in v]

    # 天线
    d.line(sc(645, 395, 828, 158), fill=CREAM, width=int(28 * k), joint="curve")
    d.ellipse(sc(828 - 30, 158 - 30, 828 + 30, 158 + 30), fill=AMBER)

    # 机身
    d.rounded_rectangle(sc(160, 380, 864, 812), radius=int(62 * k), fill=CREAM,
                        outline=(214, 204, 184), width=int(6 * k))

    # 扬声器格栅（4 条）
    y = 442
    for _ in range(4):
        d.rounded_rectangle(sc(228, y, 468, y + 34), radius=int(17 * k), fill=DARK)
        y += 72

    # 调谐旋钮（大圆盘 + 指针）
    cx, cy, r = 662, 572, 132
    d.ellipse(sc(cx - r, cy - r, cx + r, cy + r), fill=DARK)
    r2 = 110
    d.ellipse(sc(cx - r2, cy - r2, cx + r2, cy + r2), fill=CREAM)
    d.line(sc(cx, cy, cx + 74, cy - 100), fill=ACCENT, width=int(20 * k))
    d.ellipse(sc(cx - 18, cy - 18, cx + 18, cy + 18), fill=DARK)

    # 两个小旋钮
    for kx in (268, 372):
        d.ellipse(sc(kx - 34, 748 - 34, kx + 34, 748 + 34), fill=ACCENT)

    return img


def main():
    master = draw_icon(S)
    master.save(PREVIEW)
    print("preview ->", PREVIEW)

    targets = {
        "mipmap-mdpi": 48,
        "mipmap-hdpi": 72,
        "mipmap-xhdpi": 96,
        "mipmap-xxhdpi": 144,
        "mipmap-xxxhdpi": 192,
    }
    for folder, px in targets.items():
        path = os.path.join(OUT, folder, "ic_launcher.png")
        master.resize((px, px), Image.LANCZOS).save(path, "PNG", optimize=True)
        print(f"{path}  {px}x{px}  {os.path.getsize(path)} bytes")


if __name__ == "__main__":
    main()
