print("1 - Start")
import pystray
print("2 - pystray OK")
from PIL import Image, ImageDraw
print("3 - PIL OK")

img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
draw.rectangle([0, 0, 63, 63], fill=(255, 140, 0, 255))
print("4 - Image OK")

def on_ready(icon):
    print("5 - Icon ready, should be visible in tray now!")

icon = pystray.Icon("test", img, "Test")
print("6 - calling icon.run()...")
icon.run(setup=on_ready)
print("7 - run() returned (icon stopped)")
