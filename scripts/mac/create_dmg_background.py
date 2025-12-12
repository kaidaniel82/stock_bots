#!/usr/bin/env python3
"""Generate DMG background image with drag-to-install arrow."""
from PIL import Image, ImageDraw, ImageFont
import os

# DMG window size
WIDTH = 600
HEIGHT = 400

# Create image
img = Image.new('RGB', (WIDTH, HEIGHT), color=(30, 30, 30))
draw = ImageDraw.Draw(img)

# Try to use system font, fallback to default
try:
    font_large = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
    font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
except:
    font_large = ImageFont.load_default()
    font_small = font_large

# Draw arrow (simple triangle + line)
arrow_y = HEIGHT // 2
arrow_start = 220
arrow_end = 380

# Arrow line
draw.line([(arrow_start, arrow_y), (arrow_end - 20, arrow_y)], fill=(200, 200, 200), width=3)

# Arrow head
draw.polygon([
    (arrow_end, arrow_y),
    (arrow_end - 25, arrow_y - 15),
    (arrow_end - 25, arrow_y + 15)
], fill=(200, 200, 200))

# Text
draw.text((WIDTH // 2, 50), "Trailing Stop Manager", fill=(255, 255, 255), font=font_large, anchor="mm")
draw.text((WIDTH // 2, HEIGHT - 50), "Drag to Applications to install", fill=(150, 150, 150), font=font_small, anchor="mm")

# Icon placeholders text
draw.text((130, HEIGHT - 80), "App", fill=(100, 100, 100), font=font_small, anchor="mm")
draw.text((470, HEIGHT - 80), "Applications", fill=(100, 100, 100), font=font_small, anchor="mm")

# Save
output_dir = os.path.dirname(os.path.abspath(__file__))
assets_dir = os.path.join(os.path.dirname(os.path.dirname(output_dir)), 'assets')
os.makedirs(assets_dir, exist_ok=True)
output_path = os.path.join(assets_dir, 'dmg_background.png')
img.save(output_path)
print(f"Created: {output_path}")
