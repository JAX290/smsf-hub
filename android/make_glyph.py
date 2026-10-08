"""生成 ic_forwarder（磁贴/通知小图标）的白色收音机剪影。

原图是「信封+转发箭头」，与新名字 Radio 不符。
输出 5 个密度的 PNG；同时删掉会抢占优先级的 drawable-anydpi-v24 矢量。
"""
import os
from PIL import Image, ImageDraw

RES = r"C:\Users\小米\Documents\deepseek-harness\radio\src\SmsForwarder\app\src\main\res"
PREVIEW = r"C:\Users\小米\Documents\deepseek-harness\radio\glyph_preview.png"

K = 8  # 放大倍数，画完再缩小做抗锯齿
BASE = 24


def draw(size=BASE * K):
    u = size / 24.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    W = max(1, int(1.7 * u))

    def s(v):
        return v * u

    # 天线（右上）
    d.line([s(15.6), s(8.6), s(20.4), s(3.4)], fill=(255, 255, 255, 255), width=W, joint="curve")
    d.ellipse([s(20.4 - 0.9), s(3.4 - 0.9), s(20.4 + 0.9), s(3.4 + 0.9)], fill=(255, 255, 255, 255))

    # 机身轮廓
    d.rounded_rectangle([s(2.0), s(8.0), s(22.0), s(20.0)], radius=s(2.2),
                        outline=(255, 255, 255, 255), width=W)

    # 调谐盘
    d.ellipse([s(7.4 - 2.4), s(14.6 - 2.4), s(7.4 + 2.4), s(14.6 + 2.4)], fill=(255, 255, 255, 255))

    # 两条横格
    d.rounded_rectangle([s(11.6), s(11.9), s(19.6), s(13.5)], radius=s(0.8), fill=(255, 255, 255, 255))
    d.rounded_rectangle([s(11.6), s(15.7), s(19.6), s(17.3)], radius=s(0.8), fill=(255, 255, 255, 255))

    return img


def main():
    master = draw()
    master.save(PREVIEW)
    print("preview ->", PREVIEW)

    for folder, px in {"drawable-mdpi": 24, "drawable-hdpi": 36, "drawable-xhdpi": 48,
                       "drawable-xxhdpi": 72, "drawable-xxxhdpi": 96}.items():
        out = os.path.join(RES, folder, "ic_forwarder.png")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        master.resize((px, px), Image.LANCZOS).save(out, "PNG", optimize=True)
        print(f"{out}  {px}x{px}  {os.path.getsize(out)} bytes")


if __name__ == "__main__":
    main()
