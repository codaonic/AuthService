#!/usr/bin/env python3
"""Generates standard icon assets for the Auth Service.

Generates:
  - app/static/favicon.svg
  - app/static/icon.svg
  - app/static/favicon.ico (multi-resolution 16x16, 32x32, 48x48)
  - app/static/favicon-16x16.png
  - app/static/favicon-32x32.png
  - app/static/apple-touch-icon.png (180x180, opaque background for iOS)
  - frontend/public/* (mirrored copies for frontend build)

Run from the repo root:  uv run --group dev python scripts/generate_brand_assets.py
"""
import os
from PIL import Image, ImageDraw

def draw_bezier_curve(p0, p1, p2, p3, steps=30):
    points = []
    for i in range(steps + 1):
        t = i / float(steps)
        u = 1 - t
        tt = t * t
        uu = u * u
        uuu = uu * u
        ttt = tt * t
        x = uuu * p0[0] + 3 * uu * t * p1[0] + 3 * u * tt * p2[0] + ttt * p3[0]
        y = uuu * p0[1] + 3 * uu * t * p1[1] + 3 * u * tt * p2[1] + ttt * p3[1]
        points.append((x, y))
    return points

def get_shield_polygon(size):
    def s(x, y):
        return (x * size / 64.0, y * size / 64.0)

    top_right = draw_bezier_curve(s(32, 5.5), s(38, 6.2), s(45, 8.5), s(49.5, 11.2))
    shoulder_r = draw_bezier_curve(s(49.5, 11.2), s(51.8, 12.5), s(52.5, 14.5), s(52.5, 17.5))
    side_r = [s(52.5, 31)]
    bot_r = draw_bezier_curve(s(52.5, 31), s(52.5, 43.5), s(43.5, 52.8), s(32.5, 58))
    bot_tip = [s(32, 58.2), s(31.5, 58)]
    bot_l = draw_bezier_curve(s(31.5, 58), s(20.5, 52.8), s(11.5, 43.5), s(11.5, 31))
    side_l = [s(11.5, 17.5)]
    shoulder_l = draw_bezier_curve(s(11.5, 17.5), s(11.5, 14.5), s(12.2, 12.5), s(14.5, 11.2))
    top_l = draw_bezier_curve(s(14.5, 11.2), s(19, 8.5), s(26, 6.2), s(32, 5.5))

    pts = []
    for segment in [top_right, shoulder_r, side_r, bot_r, bot_tip, bot_l, side_l, shoulder_l, top_l]:
        pts.extend(segment)
    return pts

def render_icon_image(size=512):
    scale = 4 if size >= 64 else 8
    canvas_size = size * scale
    img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))

    pts = get_shield_polygon(canvas_size)

    # 1. Gradient Base Shield
    mask = Image.new("L", (canvas_size, canvas_size), 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.polygon(pts, fill=255)

    grad = Image.new("RGBA", (canvas_size, canvas_size))
    gdraw = ImageDraw.Draw(grad)

    c_start = (99, 102, 241)   # #6366F1
    c_mid = (79, 70, 229)     # #4F46E5
    c_end = (49, 46, 129)     # #312E81

    step = 2 if canvas_size <= 512 else 4
    for y in range(0, canvas_size, step):
        t = y / float(canvas_size)
        if t < 0.5:
            f = t / 0.5
            r = int(c_start[0] + (c_mid[0] - c_start[0]) * f)
            g = int(c_start[1] + (c_mid[1] - c_start[1]) * f)
            b = int(c_start[2] + (c_mid[2] - c_start[2]) * f)
        else:
            f = (t - 0.5) / 0.5
            r = int(c_mid[0] + (c_end[0] - c_mid[0]) * f)
            g = int(c_mid[1] + (c_end[1] - c_mid[1]) * f)
            b = int(c_mid[2] + (c_end[2] - c_mid[2]) * f)
        gdraw.rectangle([(0, y), (canvas_size, y + step)], fill=(r, g, b, 255))

    img.paste(grad, (0, 0), mask)

    # 2. Subtle glass rim stroke
    rim = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    rdraw = ImageDraw.Draw(rim)
    rdraw.polygon(pts, outline=(255, 255, 255, 120), width=int(1.8 * scale))
    img.alpha_composite(rim)

    # 3. Inner Graphic: Modern Keyhole + Digital Token
    def p(x, y):
        return (x * canvas_size / 64.0, y * canvas_size / 64.0)

    fg = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    fdraw = ImageDraw.Draw(fg)

    # Outer Concentric Token Ring
    ring_cx, ring_cy = p(32, 23.5)
    r_outer = 11.5 * canvas_size / 64.0
    fdraw.arc([ring_cx - r_outer, ring_cy - r_outer, ring_cx + r_outer, ring_cy + r_outer],
              start=135, end=270, fill=(255, 255, 255, 75), width=int(2.2 * scale))
    fdraw.arc([ring_cx - r_outer, ring_cy - r_outer, ring_cx + r_outer, ring_cy + r_outer],
              start=315, end=90, fill=(255, 255, 255, 75), width=int(2.2 * scale))

    # Center Key / Vault Head
    head_r = 7.5 * canvas_size / 64.0
    fdraw.ellipse([ring_cx - head_r, ring_cy - head_r, ring_cx + head_r, ring_cy + head_r],
                  fill=(255, 255, 255, 255))

    # Inner cutout
    cutout_r = 3.6 * canvas_size / 64.0
    fdraw.ellipse([ring_cx - cutout_r, ring_cy - cutout_r, ring_cx + cutout_r, ring_cy + cutout_r],
                  fill=(55, 48, 163, 255))

    # Key shaft
    shaft_w = 4.8 * canvas_size / 64.0
    shaft_top = ring_cy + 3.5 * canvas_size / 64.0
    shaft_bot = 43.5 * canvas_size / 64.0
    sx1 = ring_cx - shaft_w / 2.0
    sx2 = ring_cx + shaft_w / 2.0
    fdraw.rounded_rectangle([(sx1, shaft_top), (sx2, shaft_bot)],
                            radius=int(2.2 * scale), fill=(255, 255, 255, 255))

    # Authorization Token Teeth
    # Bit 1 (right top)
    b1_y1 = p(0, 32.5)[1]
    b1_y2 = p(0, 35.8)[1]
    b1_x2 = p(39.0, 0)[0]
    fdraw.rounded_rectangle([(sx2 - 1, b1_y1), (b1_x2, b1_y2)],
                            radius=int(1.6 * scale), fill=(255, 255, 255, 255))

    # Bit 2 (right bottom)
    b2_y1 = p(0, 38.0)[1]
    b2_y2 = p(0, 41.2)[1]
    b2_x2 = p(37.5, 0)[0]
    fdraw.rounded_rectangle([(sx2 - 1, b2_y1), (b2_x2, b2_y2)],
                            radius=int(1.6 * scale), fill=(255, 255, 255, 255))

    # Bit 3 (left security ward)
    b3_y1 = p(0, 34.8)[1]
    b3_y2 = p(0, 37.8)[1]
    b3_x1 = p(26.5, 0)[0]
    fdraw.rounded_rectangle([(b3_x1, b3_y1), (sx1 + 1, b3_y2)],
                            radius=int(1.6 * scale), fill=(255, 255, 255, 255))

    # Cyan/Azure Authentication Pulse Dot
    c_dot = p(32, 11.2)
    dr = 1.8 * canvas_size / 64.0
    fdraw.ellipse([c_dot[0] - dr, c_dot[1] - dr, c_dot[0] + dr, c_dot[1] + dr],
                  fill=(56, 189, 248, 255))

    img.alpha_composite(fg)
    return img.resize((size, size), Image.Resampling.LANCZOS)

def get_icon_svg(size=64, id_prefix="as"):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none" width="{size}" height="{size}">
  <defs>
    <linearGradient id="{id_prefix}ShieldGrad" x1="16" y1="5.5" x2="48" y2="58" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#6366F1"/>
      <stop offset="55%" stop-color="#4F46E5"/>
      <stop offset="100%" stop-color="#312E81"/>
    </linearGradient>

    <linearGradient id="{id_prefix}RimGrad" x1="32" y1="5.5" x2="32" y2="58" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#FFFFFF" stop-opacity="0.6"/>
      <stop offset="40%" stop-color="#FFFFFF" stop-opacity="0.18"/>
      <stop offset="100%" stop-color="#FFFFFF" stop-opacity="0.02"/>
    </linearGradient>

    <linearGradient id="{id_prefix}CoreGrad" x1="32" y1="16" x2="32" y2="44" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#FFFFFF"/>
      <stop offset="100%" stop-color="#EEF2FF"/>
    </linearGradient>

    <filter id="{id_prefix}Shadow" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#312E81" flood-opacity="0.35"/>
    </filter>
  </defs>

  <!-- Modern Aerodynamic Shield Base -->
  <path d="M32 5.5C38 6.2 45 8.5 49.5 11.2C51.8 12.5 52.5 14.5 52.5 17.5V31C52.5 43.5 43.5 52.8 32.5 58C32.2 58.2 31.8 58.2 31.5 58C20.5 52.8 11.5 43.5 11.5 31V17.5C11.5 14.5 12.2 12.5 14.5 11.2C19 8.5 26 6.2 32 5.5Z"
        fill="url(#{id_prefix}ShieldGrad)"
        filter="url(#{id_prefix}Shadow)"/>

  <!-- Delicate Precision Rim Stroke -->
  <path d="M32 6.8C37.8 7.5 44.5 9.7 48.8 12.3C50.6 13.4 51.2 15 51.2 17.5V31C51.2 42.8 42.8 51.6 32 56.6C21.2 51.6 12.8 42.8 12.8 31V17.5C12.8 15 13.4 13.4 15.2 12.3C19.5 9.7 26.2 7.5 32 6.8Z"
        fill="none" stroke="url(#{id_prefix}RimGrad)" stroke-width="1.2"/>

  <!-- Concentric Token Validation Ring -->
  <path d="M22 23.5C22 18 26.5 13.5 32 13.5C37.5 13.5 42 18 42 23.5"
        fill="none" stroke="#FFFFFF" stroke-opacity="0.25" stroke-width="1.8" stroke-dasharray="2 3"/>

  <!-- Azure Token Beacon Dot -->
  <circle cx="32" cy="11.2" r="1.8" fill="#38BDF8"/>

  <!-- Central Auth Key & Token Emblem -->
  <!-- Token / Vault Circular Head -->
  <circle cx="32" cy="23.5" r="7.5" fill="url(#{id_prefix}CoreGrad)"/>
  <!-- Keyway Core Hole -->
  <circle cx="32" cy="23.5" r="3.6" fill="#3730A3"/>

  <!-- Key Shaft -->
  <rect x="29.6" y="27" width="4.8" height="16.5" rx="2.4" fill="url(#{id_prefix}CoreGrad)"/>

  <!-- Authorization Token Teeth / Bits -->
  <!-- Top Right Bit (RFC 6749 / PKCE) -->
  <rect x="33.5" y="32.5" width="5.5" height="3.2" rx="1.6" fill="url(#{id_prefix}CoreGrad)"/>
  <!-- Bottom Right Bit (OpenID Token) -->
  <rect x="33.5" y="38" width="4" height="3.2" rx="1.6" fill="url(#{id_prefix}CoreGrad)"/>
  <!-- Left Security Ward (Row-Level Security) -->
  <rect x="25" y="34.8" width="5.5" height="3.2" rx="1.6" fill="url(#{id_prefix}CoreGrad)"/>
</svg>'''

def get_favicon_svg():
    return '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">
  <defs>
    <linearGradient id="favShield" x1="16" y1="5.5" x2="48" y2="58" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#6366F1"/>
      <stop offset="55%" stop-color="#4F46E5"/>
      <stop offset="100%" stop-color="#312E81"/>
    </linearGradient>
    <linearGradient id="favCore" x1="32" y1="16" x2="32" y2="44" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#FFFFFF"/>
      <stop offset="100%" stop-color="#EEF2FF"/>
    </linearGradient>
  </defs>

  <style>
    @media (prefers-color-scheme: dark) {
      .fav-beacon { fill: #38BDF8; }
    }
  </style>

  <!-- Aerodynamic Shield Base -->
  <path d="M32 5.5C38 6.2 45 8.5 49.5 11.2C51.8 12.5 52.5 14.5 52.5 17.5V31C52.5 43.5 43.5 52.8 32.5 58C32.2 58.2 31.8 58.2 31.5 58C20.5 52.8 11.5 43.5 11.5 31V17.5C11.5 14.5 12.2 12.5 14.5 11.2C19 8.5 26 6.2 32 5.5Z"
        fill="url(#favShield)"/>

  <!-- High-contrast crisp rim -->
  <path d="M32 6.8C37.8 7.5 44.5 9.7 48.8 12.3C50.6 13.4 51.2 15 51.2 17.5V31C51.2 42.8 42.8 51.6 32 56.6C21.2 51.6 12.8 42.8 12.8 31V17.5C12.8 15 13.4 13.4 15.2 12.3C19.5 9.7 26.2 7.5 32 6.8Z"
        fill="none" stroke="#FFFFFF" stroke-opacity="0.35" stroke-width="1.5"/>

  <!-- Beacon Dot -->
  <circle cx="32" cy="11.2" r="2.2" class="fav-beacon" fill="#38BDF8"/>

  <!-- Key & Token Core -->
  <circle cx="32" cy="23.5" r="7.5" fill="url(#favCore)"/>
  <circle cx="32" cy="23.5" r="3.6" fill="#3730A3"/>
  <rect x="29.6" y="27" width="4.8" height="16.5" rx="2.4" fill="url(#favCore)"/>
  <rect x="33.5" y="32.5" width="5.5" height="3.2" rx="1.6" fill="url(#favCore)"/>
  <rect x="33.5" y="38" width="4" height="3.2" rx="1.6" fill="url(#favCore)"/>
  <rect x="25" y="34.8" width="5.5" height="3.2" rx="1.6" fill="url(#favCore)"/>
</svg>'''

def main():
    target_dirs = [
        "app/static",
        "frontend/public",
    ]

    for d in target_dirs:
        os.makedirs(d, exist_ok=True)

    print("Generating vector SVGs...")
    icon_svg = get_icon_svg(64)
    fav_svg = get_favicon_svg()

    for d in target_dirs:
        with open(os.path.join(d, "icon.svg"), "w") as f:
            f.write(icon_svg)
        with open(os.path.join(d, "favicon.svg"), "w") as f:
            f.write(fav_svg)

    print("Generating raster images (PNG & ICO)...")
    img_512 = render_icon_image(512)
    # iOS fills transparent pixels with black, so flatten onto white.
    img_180 = Image.new("RGBA", (180, 180), (255, 255, 255, 255))
    img_180.alpha_composite(render_icon_image(180))
    img_180 = img_180.convert("RGB")
    img_48 = render_icon_image(48)
    img_32 = render_icon_image(32)
    img_16 = render_icon_image(16)

    for d in target_dirs:
        img_180.save(os.path.join(d, "apple-touch-icon.png"), format="PNG")
        img_32.save(os.path.join(d, "favicon-32x32.png"), format="PNG")
        img_16.save(os.path.join(d, "favicon-16x16.png"), format="PNG")
        img_512.save(
            os.path.join(d, "favicon.ico"),
            format="ICO",
            sizes=[(16, 16), (32, 32), (48, 48)],
        )

    print("Brand assets created successfully in app/static and frontend/public!")

if __name__ == "__main__":
    main()

