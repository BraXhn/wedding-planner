"""Minimal QR-kodgenerator (ISO/IEC 18004) i ren Python – bytesläge, version 1–40, nivå L/M/Q/H.
Utdata som SVG. Bygger på samma upplägg som Project Nayukis referensimplementation."""

_ECC_FORMAT = {"L": 1, "M": 0, "Q": 3, "H": 2}
_ECC_PER_BLOCK = {
    "L": [-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    "M": [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28],
    "Q": [-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    "H": [-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
}
_NUM_BLOCKS = {
    "L": [-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25],
    "M": [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49],
    "Q": [-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68],
    "H": [-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81],
}


def _raw_modules(ver: int) -> int:
    r = (16 * ver + 128) * ver + 64
    if ver >= 2:
        n = ver // 7 + 2
        r -= (25 * n - 10) * n - 55
        if ver >= 7:
            r -= 36
    return r


def _data_codewords(ver: int, ecl: str) -> int:
    return _raw_modules(ver) // 8 - _ECC_PER_BLOCK[ecl][ver] * _NUM_BLOCKS[ecl][ver]


def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree: int) -> list:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data: list, divisor: list) -> list:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


class QrCode:
    def __init__(self, text: str, ecl: str = "M"):
        data = text.encode("utf-8")
        for ver in range(1, 41):
            cc_bits = 8 if ver <= 9 else 16
            if 4 + cc_bits + len(data) * 8 <= _data_codewords(ver, ecl) * 8:
                break
        else:
            raise ValueError("För mycket data för en QR-kod")
        self.version, self.ecl, self.size = ver, ecl, ver * 4 + 17

        # --- bitström
        bits = []
        def put(val, n):
            bits.extend((val >> i) & 1 for i in reversed(range(n)))
        put(0b0100, 4)
        put(len(data), cc_bits)
        for b in data:
            put(b, 8)
        cap = _data_codewords(ver, ecl) * 8
        put(0, min(4, cap - len(bits)))
        put(0, -len(bits) % 8)
        pad = 0xEC
        while len(bits) < cap:
            put(pad, 8)
            pad ^= 0xEC ^ 0x11
        codewords = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]

        # --- felkorrigering och interfoliering
        nblocks, ecclen = _NUM_BLOCKS[ecl][ver], _ECC_PER_BLOCK[ecl][ver]
        raw = _raw_modules(ver) // 8
        nshort = nblocks - raw % nblocks
        shortlen = raw // nblocks
        div = _rs_divisor(ecclen)
        blocks, k = [], 0
        for i in range(nblocks):
            dat = codewords[k:k + shortlen - ecclen + (0 if i < nshort else 1)]
            k += len(dat)
            ecc = _rs_remainder(dat, div)
            if i < nshort:
                dat.append(0)
            blocks.append(dat + ecc)
        final = []
        for i in range(len(blocks[0])):
            for j, blk in enumerate(blocks):
                if i != shortlen - ecclen or j >= nshort:
                    final.append(blk[i])

        # --- rita
        n = self.size
        self.mod = [[False] * n for _ in range(n)]
        self.fn = [[False] * n for _ in range(n)]
        self._draw_function_patterns()
        self._draw_codewords(final)
        best, best_pen = 0, None
        for m in range(8):
            self._apply_mask(m)
            self._draw_format(m)
            pen = self._penalty()
            if best_pen is None or pen < best_pen:
                best, best_pen = m, pen
            self._apply_mask(m)  # XOR tillbaka
        self._apply_mask(best)
        self._draw_format(best)

    # ----------------------------------------------------------- funktionsmönster
    def _set_fn(self, x, y, dark):
        self.mod[y][x] = dark
        self.fn[y][x] = True

    def _draw_function_patterns(self):
        n = self.size
        for i in range(n):
            self._set_fn(6, i, i % 2 == 0)
            self._set_fn(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self._set_fn(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = self._align_positions()
        last = len(pos) - 1
        for i, a in enumerate(pos):
            for j, b in enumerate(pos):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self._set_fn(a + dx, b + dy, max(abs(dx), abs(dy)) != 1)
        self._draw_format(0)
        if self.version >= 7:
            rem = self.version
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            v = self.version << 12 | rem
            for i in range(18):
                bit = (v >> i) & 1 == 1
                a, b = n - 11 + i % 3, i // 3
                self._set_fn(a, b, bit)
                self._set_fn(b, a, bit)

    def _align_positions(self):
        if self.version == 1:
            return []
        num = self.version // 7 + 2
        step = (self.version * 8 + num * 3 + 5) // (num * 4 - 4) * 2
        return [6] + sorted(self.size - 7 - i * step for i in range(num - 1))

    def _draw_format(self, mask):
        data = _ECC_FORMAT[self.ecl] << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        b = lambda i: (bits >> i) & 1 == 1
        n = self.size
        for i in range(6):
            self._set_fn(8, i, b(i))
        self._set_fn(8, 7, b(6))
        self._set_fn(8, 8, b(7))
        self._set_fn(7, 8, b(8))
        for i in range(9, 15):
            self._set_fn(14 - i, 8, b(i))
        for i in range(8):
            self._set_fn(n - 1 - i, 8, b(i))
        for i in range(8, 15):
            self._set_fn(8, n - 15 + i, b(i))
        self._set_fn(8, n - 8, True)

    # ----------------------------------------------------------- data
    def _draw_codewords(self, data):
        n, i, total = self.size, 0, len(data) * 8
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = n - 1 - vert if upward else vert
                    if not self.fn[y][x] and i < total:
                        self.mod[y][x] = (data[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    _MASKS = [
        lambda x, y: (x + y) % 2 == 0,
        lambda x, y: y % 2 == 0,
        lambda x, y: x % 3 == 0,
        lambda x, y: (x + y) % 3 == 0,
        lambda x, y: (x // 3 + y // 2) % 2 == 0,
        lambda x, y: x * y % 2 + x * y % 3 == 0,
        lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
        lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
    ]

    def _apply_mask(self, m):
        f = self._MASKS[m]
        for y in range(self.size):
            for x in range(self.size):
                if not self.fn[y][x] and f(x, y):
                    self.mod[y][x] = not self.mod[y][x]

    def _penalty(self):
        n, m, pen = self.size, self.mod, 0
        lines = m + [[m[y][x] for y in range(n)] for x in range(n)]
        pat1 = [True, False, True, True, True, False, True, False, False, False, False]
        pat2 = pat1[::-1]
        for line in lines:
            run, prev = 0, None
            for v in line:
                if v == prev:
                    run += 1
                else:
                    if run >= 5:
                        pen += run - 2
                    run, prev = 1, v
            if run >= 5:
                pen += run - 2
            for i in range(n - 10):
                seg = line[i:i + 11]
                if seg == pat1 or seg == pat2:
                    pen += 40
        for y in range(n - 1):
            for x in range(n - 1):
                c = m[y][x]
                if c == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    pen += 3
        dark = sum(sum(r) for r in m)
        pen += (abs(dark * 20 - n * n * 10) + n * n - 1) // (n * n) * 10
        return pen

    # ----------------------------------------------------------- utdata
    def svg(self, border: int = 4, css_class: str = "qr") -> str:
        n = self.size + border * 2
        parts = [f"M{x + border},{y + border}h1v1h-1z"
                 for y in range(self.size) for x in range(self.size) if self.mod[y][x]]
        return (f'<svg xmlns="http://www.w3.org/2000/svg" class="{css_class}" viewBox="0 0 {n} {n}" '
                f'shape-rendering="crispEdges" role="img" aria-label="QR-kod">'
                f'<rect width="{n}" height="{n}" fill="#fff"/><path d="{"".join(parts)}" fill="#000"/></svg>')


def qr_svg(text: str, ecl: str = "M") -> str:
    return QrCode(text, ecl).svg()


# ----------------------------------------------------------------------- dekorativ QR för trycksaker
QR_STYLES = [("prickar", "Prickar"), ("rundad", "Rundade"), ("hjartan", "Små hjärtan"), ("romb", "Romber"),
             ("fyrkant", "Vanliga fyrkanter")]
QR_CENTERS = [("hjarta", "Hjärta i mitten"), ("ringar", "Två ringar i mitten"), ("initialer", "Initialerna i mitten"),
              ("kamera", "Kamera i mitten"), ("ingen", "Inget i mitten")]

_HEART = "M0,-.18C-.08,-.42 -.46,-.4 -.46,-.1C-.46,.14 -.2,.28 0,.44C.2,.28 .46,.14 .46,-.1C.46,-.4 .08,-.42 0,-.18Z"


def _module(style: str, x: int, y: int) -> str:
    """En mörk modul som SVG-path, centrerad i rutan (x, y)."""
    cx, cy = x + .5, y + .5
    if style == "prickar":
        r = .46
        return f"M{cx - r:.2f},{cy:.2f}a{r},{r} 0 1,0 {2 * r},0a{r},{r} 0 1,0 {-2 * r},0"
    if style == "rundad":
        return f"M{x + .3:.2f},{y + .05:.2f}h.4a.25,.25 0 0 1 .25,.25v.4a.25,.25 0 0 1 -.25,.25h-.4a.25,.25 0 0 1 -.25,-.25v-.4a.25,.25 0 0 1 .25,-.25z"
    if style == "romb":
        return f"M{cx:.2f},{y - .02:.2f}l.52,.52l-.52,.52l-.52,-.52z"
    if style == "hjartan":
        return f"M{cx:.2f},{cy - .2:.2f}c-.09,-.26 -.5,-.24 -.5,.08c0,.26 .28,.4 .5,.58c.22,-.18 .5,-.32 .5,-.58c0,-.32 -.41,-.34 -.5,-.08z"
    return f"M{x},{y}h1v1h-1z"


def _eye(style: str, x: int, y: int) -> str:
    """Hörnmarkering (7×7): yttre ring + kärna, i samma anda som modulerna."""
    if style == "prickar":
        return (f'<circle cx="{x + 3.5}" cy="{y + 3.5}" r="3" fill="none" stroke="currentColor" stroke-width="1"/>'
                f'<circle cx="{x + 3.5}" cy="{y + 3.5}" r="1.55" fill="currentColor"/>')
    if style == "hjartan":
        return (f'<rect x="{x + .5}" y="{y + .5}" width="6" height="6" rx="2" fill="none" stroke="currentColor" stroke-width="1"/>'
                f'<path transform="translate({x + 3.5} {y + 3.55}) scale(3.6)" d="{_HEART}" fill="currentColor"/>')
    ring = f'<rect x="{x + .5}" y="{y + .5}" width="6" height="6" rx="1.8" fill="none" stroke="currentColor" stroke-width="1"/>'
    if style == "rundad":
        return ring + f'<rect x="{x + 2}" y="{y + 2}" width="3" height="3" rx=".9" fill="currentColor"/>'
    if style == "romb":
        return ring + f'<path d="M{x + 3.5},{y + 1.6}l1.9,1.9l-1.9,1.9l-1.9,-1.9z" fill="currentColor"/>'
    return (f'<path d="M{x},{y}h7v7h-7zM{x + 1},{y + 1}v5h5v-5z" fill="currentColor" fill-rule="evenodd"/>'
            f'<rect x="{x + 2}" y="{y + 2}" width="3" height="3" fill="currentColor"/>')


def _center(kind: str, n: int, border: int, label: str) -> str:
    c = n / 2
    if kind == "hjarta":
        return f'<path transform="translate({c} {c + .2}) scale({n * .16:.2f})" d="{_HEART}" fill="currentColor"/>'
    if kind == "ringar":
        r = n * .055
        return (f'<g fill="none" stroke="currentColor" stroke-width="{r * .32:.2f}">'
                f'<circle cx="{c - r * .62:.2f}" cy="{c:.2f}" r="{r:.2f}"/><circle cx="{c + r * .62:.2f}" cy="{c:.2f}" r="{r:.2f}"/></g>')
    if kind == "kamera":
        w = n * .17
        return (f'<g transform="translate({c - w / 2:.2f} {c - w * .36:.2f})" fill="currentColor">'
                f'<path d="M{w * .3:.2f},0h{w * .4:.2f}l{w * .08:.2f},{w * .12:.2f}h{w * .22:.2f}v{w * .6:.2f}h-{w:.2f}v-{w * .6:.2f}h{w * .22:.2f}z"/>'
                f'<circle cx="{w / 2:.2f}" cy="{w * .42:.2f}" r="{w * .2:.2f}" fill="#fff"/><circle cx="{w / 2:.2f}" cy="{w * .42:.2f}" r="{w * .12:.2f}"/></g>')
    if kind == "initialer" and label:
        from html import escape
        return (f'<text x="{c}" y="{c}" text-anchor="middle" dominant-baseline="central" fill="currentColor" '
                f'font-family="Georgia, serif" font-style="italic" font-weight="bold" font-size="{n * .095:.2f}">{escape(label)}</text>')
    return ""


def qr_svg_fancy(text: str, style: str = "prickar", center: str = "hjarta", label: str = "", border: int = 4) -> str:
    """QR-kod med dekorativa moduler och ett motiv i mitten. Färgen är currentColor (sätts med CSS).
    Med motiv används felkorrigering H (30 %) och motivet täcker högst ~6 % av koden, så den förblir läsbar."""
    style = style if style in dict(QR_STYLES) else "prickar"
    center = center if center in dict(QR_CENTERS) else "ingen"
    if center == "initialer" and not label:
        center = "ingen"
    q = QrCode(text, "H" if center != "ingen" else "Q")
    s, n = q.size, q.size + border * 2
    eyes = [(0, 0), (s - 7, 0), (0, s - 7)]
    in_eye = lambda x, y: any(ex <= x < ex + 7 and ey <= y < ey + 7 for ex, ey in eyes)
    hole = int(s * .24) | 1 if center != "ingen" else 0   # udda antal moduler → symmetriskt kring mitten
    h0 = (s - hole) // 2
    in_hole = lambda x, y: hole and h0 <= x < h0 + hole and h0 <= y < h0 + hole
    parts = [_module(style, x + border, y + border)
             for y in range(s) for x in range(s) if q.mod[y][x] and not in_eye(x, y) and not in_hole(x, y)]
    eyes_svg = "".join(_eye(style, ex + border, ey + border) for ex, ey in eyes)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" class="qr qr-fancy" viewBox="0 0 {n} {n}" role="img" aria-label="QR-kod">'
            f'<rect class="qr-bg" width="{n}" height="{n}" fill="#fff"/>'
            f'<path d="{"".join(parts)}" fill="currentColor"/>{eyes_svg}{_center(center, n, border, label)}</svg>')


def qr_png(text: str, ecl: str = "M", scale: int = 16, border: int = 4) -> bytes:
    """PNG i hög upplösning för tryck (t.ex. 16 px per modul ≈ 600+ px)."""
    import io
    from PIL import Image
    q = QrCode(text, ecl)
    n = q.size + border * 2
    img = Image.new("1", (n, n), 1)
    px = img.load()
    for y in range(q.size):
        for x in range(q.size):
            if q.mod[y][x]:
                px[x + border, y + border] = 0
    img = img.resize((n * scale, n * scale), Image.Resampling.NEAREST)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True, dpi=(300, 300))
    return buf.getvalue()
