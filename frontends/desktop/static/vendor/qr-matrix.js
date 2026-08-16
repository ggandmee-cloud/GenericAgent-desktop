/* Minimal QR matrix (byte mode, EC M, versions 1–10, mask 0). Exposes QR.matrix(text) → 0/1 grid. */
(function (root) {
  const EXP = new Array(256), LOG = new Array(256);
  for (let i = 0, x = 1; i < 255; i++) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 0x100) x ^= 0x11d; }
  EXP[255] = EXP[0];
  const gmul = (a, b) => (a === 0 || b === 0) ? 0 : EXP[(LOG[a] + LOG[b]) % 255];
  function rsGen(n) {
    let g = [1];
    for (let i = 0; i < n; i++) {
      const ng = new Array(g.length + 1).fill(0);
      for (let j = 0; j < g.length; j++) { ng[j] ^= g[j]; ng[j + 1] ^= gmul(g[j], EXP[i]); }
      g = ng;
    }
    return g;
  }
  function rsEnc(data, n) {
    const g = rsGen(n), res = new Array(n).fill(0);
    for (let i = 0; i < data.length; i++) {
      const f = data[i] ^ res[0]; res.shift(); res.push(0);
      if (f !== 0) for (let j = 0; j < n; j++) res[j] ^= gmul(g[j + 1], f);
    }
    return res;
  }
  const CAP = [
    [1, 16, 10, [[1, 16]]], [2, 28, 16, [[1, 28]]], [3, 44, 26, [[1, 44]]], [4, 64, 18, [[2, 32]]],
    [5, 86, 24, [[2, 43]]], [6, 108, 16, [[4, 27]]], [7, 124, 18, [[4, 31]]], [8, 154, 22, [[2, 38], [2, 39]]],
    [9, 182, 22, [[3, 36], [2, 37]]], [10, 216, 26, [[4, 43], [1, 44]]]
  ];
  const ALIGN = [[], [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50]];
  const FMT_M = [0x5412, 0x5125, 0x5e7c, 0x5b4b, 0x45f9, 0x40ce, 0x4f97, 0x4aa0, 0x77c4, 0x72f3, 0x7daa, 0x789d, 0x662f, 0x6318, 0x6c41, 0x6976];
  function bytes(str) {
    const u = unescape(encodeURIComponent(str)), a = [];
    for (let i = 0; i < u.length; i++) a.push(u.charCodeAt(i));
    return a;
  }
  function build(text) {
    const src = bytes(text);
    let V = 0;
    for (const c of CAP) {
      const total = 4 + 8 + src.length * 8;
      if (total <= c[1] * 8) { V = c; break; }
    }
    if (!V) throw new Error('qr-too-long');
    const [ver, dataCw, ec, blocks] = V;
    let bits = [];
    const push = (val, len) => { for (let i = len - 1; i >= 0; i--) bits.push((val >> i) & 1); };
    push(4, 4); push(src.length, 8); src.forEach(b => push(b, 8));
    const cap = dataCw * 8;
    push(0, Math.min(4, cap - bits.length));
    while (bits.length % 8 !== 0) bits.push(0);
    const dcw = [];
    for (let i = 0; i < bits.length; i += 8) {
      let b = 0; for (let j = 0; j < 8; j++) b = (b << 1) | bits[i + j];
      dcw.push(b);
    }
    const PAD = [0xec, 0x11]; let pi = 0;
    while (dcw.length < dataCw) dcw.push(PAD[pi++ % 2]);
    const dBlocks = [], eBlocks = []; let off = 0;
    blocks.forEach(([nb, dpb]) => {
      for (let k = 0; k < nb; k++) {
        const d = dcw.slice(off, off + dpb); off += dpb;
        dBlocks.push(d); eBlocks.push(rsEnc(d, ec));
      }
    });
    const maxD = Math.max(...dBlocks.map(b => b.length)), out = [];
    for (let i = 0; i < maxD; i++) dBlocks.forEach(b => { if (i < b.length) out.push(b[i]); });
    for (let i = 0; i < ec; i++) eBlocks.forEach(b => out.push(b[i]));
    const finalBits = [];
    out.forEach(b => { for (let i = 7; i >= 0; i--) finalBits.push((b >> i) & 1); });
    return draw(ver, finalBits);
  }
  function draw(ver, data) {
    const N = ver * 4 + 17, m = [];
    for (let i = 0; i < N; i++) m.push(new Array(N).fill(null));
    const F = (r, c, v) => { if (r >= 0 && r < N && c >= 0 && c < N) m[r][c] = v; };
    const finder = (r, c) => {
      for (let i = -1; i <= 7; i++) for (let j = -1; j <= 7; j++) {
        const rr = r + i, cc = c + j;
        if (rr < 0 || rr >= N || cc < 0 || cc >= N) continue;
        const on = (i >= 0 && i <= 6 && (j === 0 || j === 6)) || (j >= 0 && j <= 6 && (i === 0 || i === 6)) || (i >= 2 && i <= 4 && j >= 2 && j <= 4);
        m[rr][cc] = on ? 1 : 0;
      }
    };
    finder(0, 0); finder(0, N - 7); finder(N - 7, 0);
    for (let i = 0; i < N; i++) {
      if (m[6][i] === null) m[6][i] = (i % 2 === 0) ? 1 : 0;
      if (m[i][6] === null) m[i][6] = (i % 2 === 0) ? 1 : 0;
    }
    const al = ALIGN[ver];
    al.forEach(r => al.forEach(c => {
      if (m[r][c] !== null) return;
      for (let i = -2; i <= 2; i++) for (let j = -2; j <= 2; j++) {
        const on = Math.max(Math.abs(i), Math.abs(j)) !== 1;
        F(r + i, c + j, on ? 1 : 0);
      }
    }));
    F(N - 8, 8, 1);
    const resFmt = (r, c) => { if (m[r][c] === null) m[r][c] = -1; };
    for (let i = 0; i <= 8; i++) { resFmt(8, i); resFmt(i, 8); }
    for (let i = 0; i < 8; i++) { resFmt(8, N - 1 - i); resFmt(N - 1 - i, 8); }
    let di = 0, up = true;
    for (let col = N - 1; col > 0; col -= 2) {
      if (col === 6) col--;
      for (let t = 0; t < N; t++) {
        const row = up ? N - 1 - t : t;
        for (let c2 = 0; c2 < 2; c2++) {
          const cc = col - c2;
          if (m[row][cc] !== null) continue;
          let bit = di < data.length ? data[di++] : 0;
          if ((row + cc) % 2 === 0) bit ^= 1;
          m[row][cc] = bit;
        }
      }
      up = !up;
    }
    const fmt = FMT_M[0], fb = [];
    for (let i = 14; i >= 0; i--) fb.push((fmt >> i) & 1);
    [[8, 0], [8, 1], [8, 2], [8, 3], [8, 4], [8, 5], [8, 7], [8, 8], [7, 8], [5, 8], [4, 8], [3, 8], [2, 8], [1, 8], [0, 8]]
      .forEach(([r, c], i) => { m[r][c] = fb[i]; });
    [[N - 1, 8], [N - 2, 8], [N - 3, 8], [N - 4, 8], [N - 5, 8], [N - 6, 8], [N - 7, 8], [8, N - 8], [8, N - 7], [8, N - 6], [8, N - 5], [8, N - 4], [8, N - 3], [8, N - 2], [8, N - 1]]
      .forEach(([r, c], i) => { m[r][c] = fb[i]; });
    for (let r = 0; r < N; r++) for (let c = 0; c < N; c++) if (m[r][c] === -1 || m[r][c] === null) m[r][c] = 0;
    return m;
  }
  function renderCanvas(text, canvas, size) {
    const m = build(text), n = m.length, s = size || 220;
    const ctx = canvas.getContext('2d');
    canvas.width = canvas.height = s;
    const cell = s / n;
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, s, s);
    ctx.fillStyle = '#111';
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (m[r][c]) ctx.fillRect(c * cell, r * cell, cell + 0.5, cell + 0.5);
  }
  root.QR = { matrix: build, renderCanvas };
})(typeof window !== 'undefined' ? window : globalThis);
