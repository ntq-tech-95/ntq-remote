"""Tạo tệp web tĩnh CapBanQuyen_DienThoai.html (0 đồng mãi mãi, chạy offline trên điện thoại)."""

import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def encrypt_seed_for_web(seed32: bytes, password: str, iterations: int = 20_000) -> dict[str, object]:
    """Mã hóa hạt giống khóa bí mật Ed25519 bằng PBKDF2-HMAC-SHA256."""
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=64)
    enc_key = derived[:32]
    mac_key = derived[32:]
    stream = hashlib.sha256(enc_key + b"\x00\x00\x00\x01").digest()
    cipher = bytes(a ^ b for a, b in zip(seed32, stream))
    tag = hmac.new(mac_key, salt + cipher, hashlib.sha256).digest()
    return {
        "salt": salt.hex(),
        "iter": iterations,
        "cipher": cipher.hex(),
        "tag": tag.hex(),
    }


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Cấp Mã Bản Quyền — Phòng Tin Học VN</title>
  <style>
    * { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { margin: 0; background: #f1f5f9; color: #0f172a; padding: 14px; }
    .card { max-width: 520px; margin: 0 auto; background: #fff; border-radius: 14px; overflow: hidden; box-shadow: 0 6px 24px rgba(15,23,42,.1); }
    .hdr { background: #1e3a8a; color: #fff; padding: 16px 18px; }
    .hdr h1 { margin: 0 0 4px; font-size: 18px; }
    .hdr p { margin: 0; font-size: 12px; color: #dbeafe; }
    .body { padding: 16px 18px; }
    label { display: block; font-size: 13px; font-weight: 700; margin: 10px 0 4px; }
    input, textarea { width: 100%; padding: 10px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 14px; }
    .row { display: flex; gap: 10px; align-items: center; }
    .row > div { flex: 1; }
    .chk { display: flex; align-items: center; gap: 8px; margin-top: 10px; font-size: 14px; font-weight: 600; }
    .chk input { width: 18px; height: 18px; }
    button { width: 100%; border: 0; border-radius: 8px; padding: 12px; font-size: 15px; font-weight: 700; cursor: pointer; margin-top: 12px; }
    .btn-primary { background: #2563eb; color: #fff; }
    .btn-copy { background: #16a34a; color: #fff; margin-top: 8px; }
    .btn-save { background: #0f172a; color: #fff; margin-top: 8px; }
    textarea { font-family: Consolas, monospace; font-size: 12px; min-height: 92px; margin-top: 6px; }
    .err { color: #b91c1c; font-size: 13px; font-weight: 600; margin-top: 8px; }
    .ok { color: #15803d; font-size: 13px; font-weight: 600; margin-top: 8px; }
  </style>
</head>
<body>
<div class="card">
  <div class="hdr">
    <h1>🔐 Cấp Bản Quyền Phòng Tin Học VN</h1>
    <p>Chạy trực tiếp trên điện thoại / trình duyệt — Miễn phí 100%, dùng cả khi mất mạng</p>
  </div>
  <div class="body">
    <label for="pwd">1. Mật khẩu mở khóa của bạn:</label>
    <input id="pwd" type="password" placeholder="Nhập mật khẩu chủ sở hữu..." />

    <label for="hwid">2. Mã máy (Hardware ID) của máy Giáo viên:</label>
    <input id="hwid" type="text" placeholder="VD: PTH-1A2B-3C4D-5E6F" autocapitalize="characters" />

    <label for="owner">3. Tên trường / Đơn vị được cấp phép:</label>
    <input id="owner" type="text" value="Phòng Tin Học Chuẩn" />

    <div class="row">
      <div>
        <label for="maxst">4. Số máy HS tối đa:</label>
        <input id="maxst" type="number" min="1" max="500" value="50" />
      </div>
      <div>
        <label for="exp">5. Ngày hết hạn:</label>
        <input id="exp" type="date" disabled />
      </div>
    </div>

    <label class="chk"><input id="perm" type="checkbox" checked onchange="togglePerm()" /> Bản quyền vĩnh viễn</label>

    <button class="btn-primary" onclick="generateKey()">🔑 Tạo Mã Bản Quyền</button>
    <div id="msg"></div>

    <label for="out">Mã bản quyền tạo ra:</label>
    <textarea id="out" readonly placeholder="Mã PTH1... sẽ hiện ở đây"></textarea>
    <button class="btn-copy" onclick="copyKey()">📋 Sao chép Mã</button>
    <button class="btn-save" onclick="downloadLic()">💾 Tải thành tệp .lic</button>
  </div>
</div>

<script>
const VAULT = __VAULT_JSON__;

// --- SHA-256 & HMAC-SHA256 & PBKDF2 (thuần JS, chạy cả trên file:// offline) ---
const K256 = new Uint32Array([
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
]);
function rotr32(x, n) { return (x >>> n) | (x << (32 - n)); }
function sha256(bytes) {
  const len = bytes.length;
  const padLen = ((len + 9 + 63) >> 6) << 6;
  const buf = new Uint8Array(padLen);
  buf.set(bytes);
  buf[len] = 0x80;
  const bitHi = Math.floor((len * 8) / 0x100000000);
  const bitLo = (len * 8) >>> 0;
  const dv = new DataView(buf.buffer);
  dv.setUint32(padLen - 8, bitHi, false);
  dv.setUint32(padLen - 4, bitLo, false);
  let h0=0x6a09e667,h1=0xbb67ae85,h2=0x3c6ef372,h3=0xa54ff53a,h4=0x510e527f,h5=0x9b05688c,h6=0x1f83d9ab,h7=0x5be0cd19;
  const w = new Uint32Array(64);
  for (let i = 0; i < padLen; i += 64) {
    for (let j = 0; j < 16; j++) w[j] = dv.getUint32(i + j * 4, false);
    for (let j = 16; j < 64; j++) {
      const s0 = rotr32(w[j-15],7) ^ rotr32(w[j-15],18) ^ (w[j-15] >>> 3);
      const s1 = rotr32(w[j-2],17) ^ rotr32(w[j-2],19) ^ (w[j-2] >>> 10);
      w[j] = (w[j-16] + s0 + w[j-7] + s1) >>> 0;
    }
    let a=h0,b=h1,c=h2,d=h3,e=h4,f=h5,g=h6,h=h7;
    for (let j = 0; j < 64; j++) {
      const S1 = rotr32(e,6) ^ rotr32(e,11) ^ rotr32(e,25);
      const ch = (e & f) ^ (~e & g);
      const t1 = (h + S1 + ch + K256[j] + w[j]) >>> 0;
      const S0 = rotr32(a,2) ^ rotr32(a,13) ^ rotr32(a,22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) >>> 0;
      h=g; g=f; f=e; e=(d+t1)>>>0; d=c; c=b; b=a; a=(t1+t2)>>>0;
    }
    h0=(h0+a)>>>0; h1=(h1+b)>>>0; h2=(h2+c)>>>0; h3=(h3+d)>>>0;
    h4=(h4+e)>>>0; h5=(h5+f)>>>0; h6=(h6+g)>>>0; h7=(h7+h)>>>0;
  }
  const out = new Uint8Array(32);
  const odv = new DataView(out.buffer);
  [h0,h1,h2,h3,h4,h5,h6,h7].forEach((v, idx) => odv.setUint32(idx*4, v, false));
  return out;
}
function hmacSha256(key, msg) {
  const k = key.length > 64 ? sha256(key) : key;
  const ipad = new Uint8Array(64 + msg.length);
  const opad = new Uint8Array(64 + 32);
  ipad.fill(0x36, 0, 64);
  opad.fill(0x5c, 0, 64);
  for (let i = 0; i < k.length; i++) { ipad[i] ^= k[i]; opad[i] ^= k[i]; }
  ipad.set(msg, 64);
  opad.set(sha256(ipad), 64);
  return sha256(opad);
}
function pbkdf2Sha256(pwdBytes, salt, iterations, dkLen) {
  const blocks = Math.ceil(dkLen / 32);
  const out = new Uint8Array(blocks * 32);
  for (let b = 1; b <= blocks; b++) {
    const sb = new Uint8Array(salt.length + 4);
    sb.set(salt);
    new DataView(sb.buffer).setUint32(salt.length, b, false);
    let u = hmacSha256(pwdBytes, sb);
    const t = new Uint8Array(u);
    for (let it = 1; it < iterations; it++) {
      u = hmacSha256(pwdBytes, u);
      for (let i = 0; i < 32; i++) t[i] ^= u[i];
    }
    out.set(t, (b - 1) * 32);
  }
  return out.slice(0, dkLen);
}

// --- SHA-512 & RFC 8032 Ed25519 (BigInt thuần JS) ---
const K512 = [
  0x428a2f98d728ae22n,0x7137449123ef65cdn,0xb5c0fbcfec4d3b2fn,0xe9b5dba58189dbbcn,
  0x3956c25bf348b538n,0x59f111f1b605d019n,0x923f82a4af194f9bn,0xab1c5ed5da6d8118n,
  0xd807aa98a3030242n,0x12835b0145706fben,0x243185be4ee4b28cn,0x550c7dc3d5ffb4e2n,
  0x72be5d74f27b896fn,0x80deb1fe3b1696b1n,0x9bdc06a725c71235n,0xc19bf174cf692694n,
  0xe49b69c19ef14ad2n,0xefbe4786384f25e3n,0x0fc19dc68b8cd5b5n,0x240ca1cc77ac9c65n,
  0x2de92c6f592b0275n,0x4a7484aa6ea6e483n,0x5cb0a9dcbd41fbd4n,0x76f988da831153b5n,
  0x983e5152ee66dfabn,0xa831c66d2db43210n,0xb00327c898fb213fn,0xbf597fc7beef0ee4n,
  0xc6e00bf33da88fc2n,0xd5a79147930aa725n,0x06ca6351e003826fn,0x142929670a0e6e70n,
  0x27b70a8546d22ffcn,0x2e1b21385c26c926n,0x4d2c6dfc5ac42aedn,0x53380d139d95b3dfn,
  0x650a73548baf63den,0x766a0abb3c77b2a8n,0x81c2c92e47edaee6n,0x92722c851482353bn,
  0xa2bfe8a14cf10364n,0xa81a664bbc423001n,0xc24b8b70d0f89791n,0xc76c51a30654be30n,
  0xd192e819d6ef5218n,0xd69906245565a910n,0xf40e35855771202an,0x106aa07032bbd1b8n,
  0x19a4c116b8d2d0c8n,0x1e376c085141ab53n,0x2748774cdf8eeb99n,0x34b0bcb5e19b48a8n,
  0x391c0cb3c5c95a63n,0x4ed8aa4ae3418acbn,0x5b9cca4f7763e373n,0x682e6ff3d6b2b8a3n,
  0x748f82ee5defb2fcn,0x78a5636f43172f60n,0x84c87814a1f0ab72n,0x8cc702081a6439ecn,
  0x90befffa23631e28n,0xa4506cebde82bde9n,0xbef9a3f7b2c67915n,0xc67178f2e372532bn,
  0xca273eceea26619cn,0xd186b8c721c0c207n,0xeada7dd6cde0eb1en,0xf57d4f7fee6ed178n,
  0x06f067aa72176fban,0x0a637dc5a2c898a6n,0x113f9804bef90daen,0x1b710b35131c471bn,
  0x28db77f523047d84n,0x32caab7b40c72493n,0x3c9ebe0a15c9bebcn,0x431d67c49c100d4cn,
  0x4cc5d4becb3e42b6n,0x597f299cfc657e2an,0x5fcb6fab3ad6faecn,0x6c44198c4a475817n
];
const M64 = (1n << 64n) - 1n;
function rotr64(x, n) { return ((x >> BigInt(n)) | (x << BigInt(64 - n))) & M64; }
function sha512(bytes) {
  const len = bytes.length;
  const padLen = Math.ceil((len + 17) / 128) * 128;
  const buf = new Uint8Array(padLen);
  buf.set(bytes);
  buf[len] = 0x80;
  let bitLen = BigInt(len) * 8n;
  for (let i = 0; i < 16; i++) {
    buf[padLen - 1 - i] = Number(bitLen & 0xffn);
    bitLen >>= 8n;
  }
  let H = [
    0x6a09e667f3bcc908n,0xbb67ae8584caa73bn,0x3c6ef372fe94f82bn,0xa54ff53a5f1d36f1n,
    0x510e527fade682d1n,0x9b05688c2b3e6c1fn,0x1f83d9abfb41bd6bn,0x5be0cd19137e2179n
  ];
  const w = new Array(80);
  for (let i = 0; i < padLen; i += 128) {
    for (let j = 0; j < 16; j++) {
      let v = 0n;
      for (let k = 0; k < 8; k++) v = (v << 8n) | BigInt(buf[i + j * 8 + k]);
      w[j] = v;
    }
    for (let j = 16; j < 80; j++) {
      const s0 = rotr64(w[j-15],1) ^ rotr64(w[j-15],8) ^ (w[j-15] >> 7n);
      const s1 = rotr64(w[j-2],19) ^ rotr64(w[j-2],61) ^ (w[j-2] >> 6n);
      w[j] = (w[j-16] + s0 + w[j-7] + s1) & M64;
    }
    let [a,b,c,d,e,f,g,h] = H;
    for (let j = 0; j < 80; j++) {
      const S1 = rotr64(e,14) ^ rotr64(e,18) ^ rotr64(e,41);
      const ch = (e & f) ^ ((~e & M64) & g);
      const t1 = (h + S1 + ch + K512[j] + w[j]) & M64;
      const S0 = rotr64(a,28) ^ rotr64(a,34) ^ rotr64(a,39);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) & M64;
      h=g; g=f; f=e; e=(d+t1)&M64; d=c; c=b; b=a; a=(t1+t2)&M64;
    }
    H = [(H[0]+a)&M64,(H[1]+b)&M64,(H[2]+c)&M64,(H[3]+d)&M64,(H[4]+e)&M64,(H[5]+f)&M64,(H[6]+g)&M64,(H[7]+h)&M64];
  }
  const out = new Uint8Array(64);
  for (let i = 0; i < 8; i++) {
    let v = H[i];
    for (let k = 7; k >= 0; k--) { out[i * 8 + k] = Number(v & 0xffn); v >>= 8n; }
  }
  return out;
}

const P_ED = (1n << 255n) - 19n;
const L_ED = (1n << 252n) + 27742317777372353535851937790883648493n;
function modP(a) { const r = a % P_ED; return r >= 0n ? r : r + P_ED; }
function powMod(base, exp, mod) {
  let res = 1n, b = base % mod;
  if (b < 0n) b += mod;
  let e = exp;
  while (e > 0n) {
    if (e & 1n) res = (res * b) % mod;
    b = (b * b) % mod;
    e >>= 1n;
  }
  return res;
}
function invModP(a) { return powMod(a, P_ED - 2n, P_ED); }
const D_ED = modP(-121665n * invModP(121666n));
const G_ED = [
  15112221349535400772501151409588531511454012693041857206046113283949847762202n,
  46316835694926478169428394003475163141307993866256225615783033603165251855960n,
  1n,
  modP(15112221349535400772501151409588531511454012693041857206046113283949847762202n * 46316835694926478169428394003475163141307993866256225615783033603165251855960n)
];
function ptAdd(P, Q) {
  const [X1,Y1,Z1,T1] = P, [X2,Y2,Z2,T2] = Q;
  const A = modP((Y1 - X1) * (Y2 - X2));
  const B = modP((Y1 + X1) * (Y2 + X2));
  const C = modP(2n * T1 * T2 * D_ED);
  const D = modP(2n * Z1 * Z2);
  const E = modP(B - A), F = modP(D - C), G = modP(D + C), H = modP(B + A);
  return [modP(E * F), modP(G * H), modP(F * G), modP(E * H)];
}
function ptMul(s, P) {
  let R = [0n, 1n, 1n, 0n], Q = P, k = s;
  while (k > 0n) {
    if (k & 1n) R = ptAdd(R, Q);
    Q = ptAdd(Q, Q);
    k >>= 1n;
  }
  return R;
}
function leBytesToBigInt(bytes) {
  let r = 0n;
  for (let i = bytes.length - 1; i >= 0; i--) r = (r << 8n) | BigInt(bytes[i]);
  return r;
}
function bigIntToLe32(n) {
  const out = new Uint8Array(32);
  let v = n;
  for (let i = 0; i < 32; i++) { out[i] = Number(v & 0xffn); v >>= 8n; }
  return out;
}
function encodePoint(P) {
  const zInv = invModP(P[2]);
  const x = modP(P[0] * zInv);
  const y = modP(P[1] * zInv);
  const b = bigIntToLe32(y);
  if (x & 1n) b[31] |= 0x80;
  return b;
}
function ed25519Sign(seed32, msgBytes) {
  const h = sha512(seed32);
  const aBytes = h.slice(0, 32);
  aBytes[0] &= 248; aBytes[31] &= 127; aBytes[31] |= 64;
  const a = leBytesToBigInt(aBytes);
  const prefix = h.slice(32, 64);
  const A = encodePoint(ptMul(a, G_ED));

  const rInput = new Uint8Array(32 + msgBytes.length);
  rInput.set(prefix); rInput.set(msgBytes, 32);
  const r = leBytesToBigInt(sha512(rInput)) % L_ED;
  const R = encodePoint(ptMul(r, G_ED));

  const kInput = new Uint8Array(64 + msgBytes.length);
  kInput.set(R); kInput.set(A, 32); kInput.set(msgBytes, 64);
  const k = leBytesToBigInt(sha512(kInput)) % L_ED;
  const S = (r + k * a) % L_ED;

  const sig = new Uint8Array(64);
  sig.set(R); sig.set(bigIntToLe32(S), 32);
  return sig;
}

function hexToBytes(hex) {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16);
  return out;
}
function b64u(bytes) {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function togglePerm() {
  document.getElementById("exp").disabled = document.getElementById("perm").checked;
}
function unlockSeed(password) {
  const pwdBytes = new TextEncoder().encode(password);
  const salt = hexToBytes(VAULT.salt);
  const cipher = hexToBytes(VAULT.cipher);
  const derived = pbkdf2Sha256(pwdBytes, salt, VAULT.iter, 64);
  const encKey = derived.slice(0, 32);
  const macKey = derived.slice(32, 64);

  const checkBuf = new Uint8Array(salt.length + cipher.length);
  checkBuf.set(salt); checkBuf.set(cipher, salt.length);
  const tag = hmacSha256(macKey, checkBuf);
  const expectedTag = hexToBytes(VAULT.tag);
  let diff = 0;
  for (let i = 0; i < 32; i++) diff |= (tag[i] ^ expectedTag[i]);
  if (diff !== 0) return null;

  const streamIn = new Uint8Array(36);
  streamIn.set(encKey); streamIn[35] = 1;
  const stream = sha256(streamIn);
  const seed = new Uint8Array(32);
  for (let i = 0; i < 32; i++) seed[i] = cipher[i] ^ stream[i];
  return seed;
}

function generateKey() {
  const msgEl = document.getElementById("msg");
  msgEl.className = ""; msgEl.textContent = "";
  const pwd = document.getElementById("pwd").value;
  const hwid = document.getElementById("hwid").value.trim().toUpperCase();
  const owner = document.getElementById("owner").value.trim() || "Đơn vị được cấp phép";
  const maxSt = parseInt(document.getElementById("maxst").value, 10) || 40;
  const perm = document.getElementById("perm").checked;
  const exp = perm ? "VINH_VIEN" : document.getElementById("exp").value;

  if (!pwd) { msgEl.className="err"; msgEl.textContent="Vui lòng nhập mật khẩu mở khóa."; return; }
  if (!hwid.startsWith("PTH-")) { msgEl.className="err"; msgEl.textContent="Mã máy phải bắt đầu bằng PTH-"; return; }
  if (!perm && !exp) { msgEl.className="err"; msgEl.textContent="Vui lòng chọn ngày hết hạn."; return; }

  const seed = unlockSeed(pwd);
  if (!seed) { msgEl.className="err"; msgEl.textContent="Sai mật khẩu mở khóa!"; return; }

  const today = new Date().toISOString().slice(0, 10);
  const payloadObj = {
    hwid: hwid,
    owner: owner,
    max_students: Math.max(1, maxSt),
    expires_at: exp,
    issued_at: today
  };
  const payloadBytes = new TextEncoder().encode(JSON.stringify(payloadObj));
  const sigBytes = ed25519Sign(seed, payloadBytes);
  const key = "PTH1." + b64u(payloadBytes) + "." + b64u(sigBytes);
  document.getElementById("out").value = key;
  msgEl.className = "ok";
  msgEl.textContent = "✔ Đã tạo Mã bản quyền hợp lệ!";
}

function copyKey() {
  const out = document.getElementById("out");
  if (!out.value) return;
  out.select();
  if (navigator.clipboard) navigator.clipboard.writeText(out.value).catch(() => {});
  document.execCommand("copy");
  const msgEl = document.getElementById("msg");
  msgEl.className = "ok";
  msgEl.textContent = "✔ Đã sao chép Mã bản quyền!";
}

function downloadLic() {
  const val = document.getElementById("out").value.trim();
  if (!val) return;
  const hwid = document.getElementById("hwid").value.trim().toUpperCase() || "BanQuyen";
  const blob = new Blob([val], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "BanQuyen_" + hwid + ".lic";
  a.click();
}
</script>
</body>
</html>
"""


def build_mobile_html(
    password: str,
    private_key_path: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    pem = private_key_path or (Path(__file__).resolve().parent / "private_key.pem")
    priv = serialization.load_pem_private_key(pem.read_bytes(), password=None)
    if not isinstance(priv, Ed25519PrivateKey):
        raise ValueError("Khóa bí mật không hợp lệ.")
    seed32 = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    vault = encrypt_seed_for_web(seed32, password)
    html = _HTML_TEMPLATE.replace("__VAULT_JSON__", json.dumps(vault))
    out = output_path or (Path(__file__).resolve().parent / "CapBanQuyen_DienThoai.html")
    out.write_text(html, encoding="utf-8")
    if output_path is None:
        upload_dir = Path(__file__).resolve().parent / "WebCapKey_Upload"
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / "index.html").write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        pwd = sys.argv[1]
    else:
        print("=== TAO TRANG WEB CAP BAN QUYEN DIEN THOAI (0 DONG) ===")
        pwd = input("Nhap mat khau ban muon dung de khoa file HTML (mac dinh PhongTin@2026): ").strip() or "PhongTin@2026"
    out_file = build_mobile_html(pwd)
    print(f"Thanh cong! Da tao file: {out_file}")
