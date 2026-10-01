"""A small, dependency-free QR code encoder for the sync links.

Byte mode, error correction level M, versions 1–10 (up to 213 bytes — a sync
link is about 40). Written out here so the site needs nothing beyond Flask:
a missing optional package must never be the reason a QR code is blank.

    svg = qr_svg("https://example.org/sync/12345678")

Follows ISO/IEC 18004: Reed–Solomon over GF(256), the standard placement,
all eight masks scored with the four penalty rules, best one kept.
"""

from __future__ import annotations

# version -> (EC codewords per block, [(blocks, data codewords per block), ...])
_LEVEL_M = {
    1: (10, [(1, 16)]),
    2: (16, [(1, 28)]),
    3: (26, [(1, 44)]),
    4: (18, [(2, 32)]),
    5: (24, [(2, 43)]),
    6: (16, [(4, 27)]),
    7: (18, [(4, 31)]),
    8: (22, [(2, 38), (2, 39)]),
    9: (22, [(3, 36), (2, 37)]),
    10: (26, [(4, 43), (1, 44)]),
}

_ALIGNMENT = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

_EC_LEVEL_M_BITS = 0b00

# --- GF(256) arithmetic, primitive polynomial x^8+x^4+x^3+x^2+1 ------------

_EXP = [0] * 512
_LOG = [0] * 256
_value = 1
for _i in range(255):
    _EXP[_i] = _value
    _LOG[_value] = _i
    _value <<= 1
    if _value & 0x100:
        _value ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(degree: int) -> list[int]:
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            nxt[j] ^= coef
            nxt[j + 1] ^= _gf_mul(coef, _EXP[i])
        poly = nxt
    return poly


def _rs_remainder(data: list[int], degree: int) -> list[int]:
    gen = _rs_generator(degree)
    rem = list(data) + [0] * degree
    for i in range(len(data)):
        factor = rem[i]
        if factor:
            for j in range(1, len(gen)):
                rem[i + j] ^= _gf_mul(gen[j], factor)
    return rem[len(data):]


# --- data encoding ----------------------------------------------------------

def _capacity(version: int) -> int:
    _, groups = _LEVEL_M[version]
    return sum(blocks * size for blocks, size in groups)


def _pick_version(length: int) -> int:
    for version in _LEVEL_M:
        count_bits = 8 if version < 10 else 16
        if 4 + count_bits + 8 * length <= 8 * _capacity(version):
            return version
    raise ValueError("text too long for a QR code here")


def _codewords(payload: bytes, version: int) -> list[int]:
    count_bits = 8 if version < 10 else 16
    capacity = _capacity(version) * 8
    bits: list[int] = []

    def put(value: int, width: int) -> None:
        bits.extend((value >> (width - 1 - i)) & 1 for i in range(width))

    put(0b0100, 4)  # byte mode
    put(len(payload), count_bits)
    for byte in payload:
        put(byte, 8)
    put(0, min(4, capacity - len(bits)))  # terminator
    if len(bits) % 8:
        put(0, 8 - len(bits) % 8)
    pad = 0
    while len(bits) < capacity:
        put((0xEC, 0x11)[pad % 2], 8)
        pad += 1
    data = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]

    ec_len, groups = _LEVEL_M[version]
    blocks: list[list[int]] = []
    offset = 0
    for count, size in groups:
        for _ in range(count):
            blocks.append(data[offset:offset + size])
            offset += size
    ecc = [_rs_remainder(block, ec_len) for block in blocks]

    result: list[int] = []
    for i in range(max(len(block) for block in blocks)):
        result.extend(block[i] for block in blocks if i < len(block))
    for i in range(ec_len):
        result.extend(block[i] for block in ecc)
    return result


# --- matrix -----------------------------------------------------------------

def _bch(value: int, generator: int, total: int) -> int:
    degree = generator.bit_length() - 1
    rem = value << degree
    for shift in range(total - 1, degree - 1, -1):
        if rem >> shift & 1:
            rem ^= generator << (shift - degree)
    return (value << degree) | rem


_MASKS = [
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
]


class _Matrix:
    def __init__(self, version: int):
        self.version = version
        self.size = 17 + 4 * version
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.fixed = [[False] * self.size for _ in range(self.size)]
        self._function_patterns()

    def set(self, r: int, c: int, dark: bool) -> None:
        self.dark[r][c] = dark
        self.fixed[r][c] = True

    def _function_patterns(self) -> None:
        n = self.size
        for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):
            for dr in range(-1, 8):
                for dc in range(-1, 8):
                    r, c = r0 + dr, c0 + dc
                    if 0 <= r < n and 0 <= c < n:
                        ring = max(abs(dr - 3), abs(dc - 3))
                        self.set(r, c, ring != 2 and ring != 4)
        for i in range(8, n - 8):
            self.set(6, i, i % 2 == 0)
            self.set(i, 6, i % 2 == 0)
        centres = _ALIGNMENT[self.version]
        corners = {(6, 6), (6, n - 7), (n - 7, 6)}
        for r in centres:
            for c in centres:
                if (r, c) in corners:
                    continue  # would sit on a finder pattern
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        self.set(r + dr, c + dc, max(abs(dr), abs(dc)) != 1)
        # Reserve format areas (filled per mask) and the dark module.
        for i in range(9):
            self.fixed[8][i] = self.fixed[i][8] = True
        for i in range(8):
            self.fixed[8][n - 1 - i] = self.fixed[n - 1 - i][8] = True
        self.set(n - 8, 8, True)
        if self.version >= 7:
            info = _bch(self.version, 0x1F25, 18)
            for i in range(18):
                bit = bool(info >> i & 1)
                a, b = n - 11 + i % 3, i // 3
                self.set(a, b, bit)
                self.set(b, a, bit)

    def place(self, codewords: list[int]) -> None:
        bits = [(byte >> (7 - i)) & 1 for byte in codewords for i in range(8)]
        index = 0
        n = self.size
        upward = True
        col = n - 1
        while col > 0:
            if col == 6:
                col -= 1
            rows = range(n - 1, -1, -1) if upward else range(n)
            for r in rows:
                for c in (col, col - 1):
                    if not self.fixed[r][c]:
                        self.dark[r][c] = index < len(bits) and bits[index] == 1
                        index += 1
            upward = not upward
            col -= 2

    def masked(self, mask: int) -> list[list[bool]]:
        n = self.size
        grid = [row[:] for row in self.dark]
        test = _MASKS[mask]
        for r in range(n):
            for c in range(n):
                if not self.fixed[r][c] and test(r, c):
                    grid[r][c] = not grid[r][c]
        info = _bch((_EC_LEVEL_M_BITS << 3) | mask, 0x537, 15) ^ 0x5412
        bits = [bool(info >> i & 1) for i in range(15)]
        # First copy, around the top-left finder.
        for i in range(6):
            grid[i][8] = bits[i]
        grid[7][8] = bits[6]
        grid[8][8] = bits[7]
        grid[8][7] = bits[8]
        for i in range(9, 15):
            grid[8][14 - i] = bits[i]
        # Second copy, split between the other two finders.
        for i in range(8):
            grid[8][n - 1 - i] = bits[i]
        for i in range(8, 15):
            grid[n - 15 + i][8] = bits[i]
        grid[n - 8][8] = True
        return grid


_FINDER_LEFT = [False] * 4 + [True, False, True, True, True, False, True]
_FINDER_RIGHT = [True, False, True, True, True, False, True] + [False] * 4


def _penalty(grid: list[list[bool]]) -> int:
    n = len(grid)
    score = 0
    lines = grid + [list(col) for col in zip(*grid)]
    for line in lines:
        run = 1
        for i in range(1, n + 1):
            if i < n and line[i] == line[i - 1]:
                run += 1
            else:
                if run >= 5:
                    score += run - 2
                run = 1
        # A finder-like 1:1:3:1:1 run with four light modules on one side;
        # the quiet zone counts as light.
        padded = [False] * 4 + line + [False] * 4
        for i in range(len(padded) - 10):
            if padded[i:i + 11] in (_FINDER_LEFT, _FINDER_RIGHT):
                score += 40
    for r in range(n - 1):
        for c in range(n - 1):
            value = grid[r][c]
            if value == grid[r][c + 1] == grid[r + 1][c] == grid[r + 1][c + 1]:
                score += 3
    dark = sum(sum(row) for row in grid)
    score += abs(dark * 20 - n * n * 10) // (n * n) * 10
    return score


def qr_matrix(text: str, mask: int | None = None) -> list[list[bool]]:
    """The module grid for ``text``, without the quiet zone."""
    payload = text.encode("utf-8")
    version = _pick_version(len(payload))
    matrix = _Matrix(version)
    matrix.place(_codewords(payload, version))
    if mask is not None:
        return matrix.masked(mask)
    return min((matrix.masked(m) for m in range(8)), key=_penalty)


def qr_svg(text: str, scale: int = 6, border: int = 4) -> str:
    """Black-on-white SVG of the QR code, with a quiet zone of ``border``."""
    grid = qr_matrix(text)
    size = len(grid) + 2 * border
    path = "".join(
        f"M{c + border},{r + border}h1v1h-1z"
        for r, row in enumerate(grid)
        for c, dark in enumerate(row)
        if dark
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size * scale}" height="{size * scale}" '
        f'viewBox="0 0 {size} {size}" shape-rendering="crispEdges">'
        f'<rect width="{size}" height="{size}" fill="#fff"/>'
        f'<path d="{path}" fill="#000"/></svg>'
    )
