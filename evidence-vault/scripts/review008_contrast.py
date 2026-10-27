def srgb(c):
    c = c/255
    return c/12.92 if c <= 0.04045 else ((c+0.055)/1.055)**2.4
def lum(r,g,b):
    return 0.2126*srgb(r)+0.7152*srgb(g)+0.0722*srgb(b)
def contrast(fg,bg):
    l1,l2 = lum(*fg), lum(*bg)
    hi,lo = max(l1,l2), min(l1,l2)
    return (hi+0.05)/(lo+0.05)

# N-6: eb-btn: white text on color-mix(in srgb, var(--danger) 82%, black), danger=#E06C5F
danger = (0xE0,0x6C,0x5F)
mixed = tuple(round(c*0.82) for c in danger)
print("color-mix 82% #E06C5F + 18% black =", "#%02X%02X%02X" % mixed)
print("N-6 eb-btn contrast #fff on mixed: %.2f:1" % contrast((255,255,255), mixed))
# also with CSS rounding (round half up on exact value)
mixed2 = tuple(int(c*0.82+0.5) for c in danger)
print("  (int-rounded variant same:", tuple(int(c*0.82+0.5) for c in danger)==mixed, ")")

# placeholder rgb(147,158,169) on bg #0D1014
ph = (147,158,169); bg = (0x0D,0x10,0x14)
print("placeholder rgb(147,158,169) on #0D1014: %.2f:1" % contrast(ph,bg))
# --text-dim #939EA9 on #0D1014
td = (0x93,0x9E,0xA9)
print("--text-dim #939EA9 on #0D1014: %.2f:1" % contrast(td,bg))
# factory tab gold rgb(212,172,85) vs adjacent? not needed
