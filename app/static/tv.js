/* ================================================================
   MISC — open calls on a screen. The home page of the app.
   Data comes from the server (window.TV, see app/tv.py): open calls, a series shown once
   (its next call), grouped by field. Drawn on a canvas at least 3840×2160 units large that
   is stretched to fill the whole window or screen, whatever its size and shape.
   Keys: → / space next · ← previous · P pause · F fullscreen · S search
   ================================================================ */
var TV = window.TV || {config: {}, fields: [], items: []};
var CONFIG = {slideSeconds: 22, perPage: 4, autoplay: true, showCover: true, markUrgent: true,
              urgentDays: 14, today: '', reloadMinutes: 60};
Object.keys(TV.config || {}).forEach(function (k) { CONFIG[k] = TV.config[k]; });
var CALLS = TV.items || [];
var FIELDS = TV.fields || [];
var MISC_LOGO = '<img class="logo" alt="MISC — Music Innovation Studies Centre" src="' + CONFIG.logo + '">';

/* ================================================================
   1) QR kodų generatorius (savarankiškas, veikia be interneto)
   ================================================================ */
/* Minimal QR Code encoder — byte mode, ECC level M, versions 1-10.
   Returns a boolean matrix (true = dark). Self-contained, no dependencies. */
(function (root) {
  'use strict';

  // ---- GF(256) tables, primitive polynomial 0x11D ----
  var EXP = new Uint8Array(512), LOG = new Uint8Array(256);
  (function () {
    var x = 1;
    for (var i = 0; i < 255; i++) {
      EXP[i] = x; LOG[x] = i;
      x <<= 1;
      if (x & 0x100) x ^= 0x11D;
    }
    for (var j = 255; j < 512; j++) EXP[j] = EXP[j - 255];
  })();
  function gmul(a, b) { return (a === 0 || b === 0) ? 0 : EXP[LOG[a] + LOG[b]]; }

  // ---- per-version tables (index = version) for ECC level M ----
  var ECC_PER_BLOCK_M = [0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26];
  var NUM_BLOCKS_M    = [0,  1,  1,  1,  2,  2,  4,  4,  4,  5,  5];

  function rawDataModules(ver) {
    var r = (16 * ver + 128) * ver + 64;
    if (ver >= 2) {
      var n = Math.floor(ver / 7) + 2;
      r -= (25 * n - 10) * n - 55;
      if (ver >= 7) r -= 36;
    }
    return r;
  }
  function totalCodewords(ver) { return Math.floor(rawDataModules(ver) / 8); }
  function dataCodewords(ver) {
    return totalCodewords(ver) - ECC_PER_BLOCK_M[ver] * NUM_BLOCKS_M[ver];
  }

  function alignPositions(ver) {
    if (ver === 1) return [];
    var n = Math.floor(ver / 7) + 2;
    var step = Math.ceil((ver * 4 + 4) / (n - 1) / 2) * 2;
    var res = [6];
    for (var pos = ver * 4 + 10; res.length < n; pos -= step) res.splice(1, 0, pos);
    return res;
  }

  // ---- Reed-Solomon ----
  function rsGenerator(degree) {
    var poly = [1];
    for (var i = 0; i < degree; i++) {
      var next = new Array(poly.length + 1).fill(0);
      for (var j = 0; j < poly.length; j++) {
        next[j] ^= gmul(poly[j], 1);
        next[j + 1] ^= gmul(poly[j], EXP[i]);
      }
      poly = next;
    }
    return poly; // length degree+1, leading coeff 1
  }
  function rsRemainder(data, degree) {
    var gen = rsGenerator(degree);
    var res = new Array(degree).fill(0);
    for (var i = 0; i < data.length; i++) {
      var factor = data[i] ^ res[0];
      res.shift(); res.push(0);
      for (var j = 0; j < degree; j++) res[j] ^= gmul(gen[j + 1], factor);
    }
    return res;
  }

  // ---- bit buffer ----
  function BitBuf() { this.bits = []; }
  BitBuf.prototype.put = function (val, len) {
    for (var i = len - 1; i >= 0; i--) this.bits.push((val >>> i) & 1);
  };

  function utf8Bytes(str) {
    var out = [], enc = encodeURIComponent(str);
    for (var i = 0; i < enc.length; i++) {
      if (enc[i] === '%') { out.push(parseInt(enc.substr(i + 1, 2), 16)); i += 2; }
      else out.push(enc.charCodeAt(i));
    }
    return out;
  }

  function chooseVersion(byteLen) {
    for (var v = 1; v <= 10; v++) {
      var headerBits = 4 + (v <= 9 ? 8 : 16);
      if (dataCodewords(v) * 8 >= headerBits + byteLen * 8) return v;
    }
    throw new Error('QR: data too long (max version 10 supported)');
  }

  function buildCodewords(bytes, ver) {
    var bb = new BitBuf();
    bb.put(4, 4);                                   // byte mode
    bb.put(bytes.length, ver <= 9 ? 8 : 16);        // character count
    for (var i = 0; i < bytes.length; i++) bb.put(bytes[i], 8);

    var capacity = dataCodewords(ver) * 8;
    for (var t = 0; t < 4 && bb.bits.length < capacity; t++) bb.bits.push(0);
    while (bb.bits.length % 8 !== 0) bb.bits.push(0);

    var dat = [];
    for (var b = 0; b < bb.bits.length; b += 8) {
      var v = 0;
      for (var k = 0; k < 8; k++) v = (v << 1) | bb.bits[b + k];
      dat.push(v);
    }
    var padBytes = [0xEC, 0x11], p = 0;
    while (dat.length < dataCodewords(ver)) dat.push(padBytes[p++ % 2]);

    // split into blocks and compute ECC
    var numBlocks = NUM_BLOCKS_M[ver], eccLen = ECC_PER_BLOCK_M[ver];
    var shortLen = Math.floor(dat.length / numBlocks);
    var numLong = dat.length % numBlocks;
    var blocks = [], eccs = [], off = 0;
    for (var bi = 0; bi < numBlocks; bi++) {
      var len = shortLen + (bi >= numBlocks - numLong ? 1 : 0);
      var blk = dat.slice(off, off + len); off += len;
      blocks.push(blk);
      eccs.push(rsRemainder(blk, eccLen));
    }
    // interleave
    var out = [], maxLen = shortLen + (numLong > 0 ? 1 : 0);
    for (var c = 0; c < maxLen; c++)
      for (var bj = 0; bj < numBlocks; bj++)
        if (c < blocks[bj].length) out.push(blocks[bj][c]);
    for (var e = 0; e < eccLen; e++)
      for (var bk = 0; bk < numBlocks; bk++) out.push(eccs[bk][e]);
    return out;
  }

  // ---- matrix construction ----
  function makeMatrix(ver, codewords) {
    var size = ver * 4 + 17;
    var m = [], reserved = [];
    for (var i = 0; i < size; i++) {
      m.push(new Array(size).fill(false));
      reserved.push(new Array(size).fill(false));
    }
    function setF(x, y, dark) {
      if (x < 0 || y < 0 || x >= size || y >= size) return;
      m[y][x] = dark; reserved[y][x] = true;
    }
    // finder patterns + separators
    function finder(cx, cy) {
      for (var dy = -4; dy <= 4; dy++)
        for (var dx = -4; dx <= 4; dx++) {
          var d = Math.max(Math.abs(dx), Math.abs(dy));
          setF(cx + dx, cy + dy, d !== 2 && d <= 3);
        }
    }
    finder(3, 3); finder(size - 4, 3); finder(3, size - 4);

    // timing patterns
    for (var t = 0; t < size; t++) {
      if (!reserved[6][t]) setF(t, 6, t % 2 === 0);
      if (!reserved[t][6]) setF(6, t, t % 2 === 0);
    }
    // alignment patterns
    var ap = alignPositions(ver);
    for (var a = 0; a < ap.length; a++)
      for (var b = 0; b < ap.length; b++) {
        if ((a === 0 && b === 0) || (a === 0 && b === ap.length - 1) ||
            (a === ap.length - 1 && b === 0)) continue;
        for (var dy2 = -2; dy2 <= 2; dy2++)
          for (var dx2 = -2; dx2 <= 2; dx2++)
            setF(ap[b] + dx2, ap[a] + dy2, Math.max(Math.abs(dx2), Math.abs(dy2)) !== 1);
      }
    // reserve format info areas
    for (var f = 0; f < 9; f++) {
      if (!reserved[8][f]) { reserved[8][f] = true; }
      if (!reserved[f][8]) { reserved[f][8] = true; }
    }
    for (var g = 0; g < 8; g++) {
      reserved[8][size - 1 - g] = true;
      reserved[size - 1 - g][8] = true;
    }
    setF(8, size - 8, true); // dark module

    // version info (v >= 7)
    if (ver >= 7) {
      var rem = ver;
      for (var q = 0; q < 12; q++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1F25);
      var vbits = (ver << 12) | rem;
      for (var k = 0; k < 18; k++) {
        var bit = ((vbits >>> k) & 1) === 1;
        var r = Math.floor(k / 3), cc = k % 3;
        setF(size - 11 + cc, r, bit);
        setF(r, size - 11 + cc, bit);
      }
    }

    // place data bits, zigzag from bottom-right
    var bitIdx = 0;
    function nextBit() {
      if (bitIdx >= codewords.length * 8) return false;
      var v = (codewords[bitIdx >>> 3] >>> (7 - (bitIdx & 7))) & 1;
      bitIdx++;
      return v === 1;
    }
    for (var right = size - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (var vert = 0; vert < size; vert++) {
        for (var j2 = 0; j2 < 2; j2++) {
          var x = right - j2;
          var upward = ((right + 1) & 2) === 0;
          var y = upward ? size - 1 - vert : vert;
          if (!reserved[y][x]) m[y][x] = nextBit();
        }
      }
    }
    return { m: m, reserved: reserved, size: size };
  }

  function applyMask(m, reserved, size, mask) {
    var out = m.map(function (row) { return row.slice(); });
    for (var y = 0; y < size; y++)
      for (var x = 0; x < size; x++) {
        if (reserved[y][x]) continue;
        var inv;
        switch (mask) {
          case 0: inv = (x + y) % 2 === 0; break;
          case 1: inv = y % 2 === 0; break;
          case 2: inv = x % 3 === 0; break;
          case 3: inv = (x + y) % 3 === 0; break;
          case 4: inv = (Math.floor(y / 2) + Math.floor(x / 3)) % 2 === 0; break;
          case 5: inv = ((x * y) % 2 + (x * y) % 3) === 0; break;
          case 6: inv = (((x * y) % 2 + (x * y) % 3) % 2) === 0; break;
          case 7: inv = (((x + y) % 2 + (x * y) % 3) % 2) === 0; break;
        }
        if (inv) out[y][x] = !out[y][x];
      }
    return out;
  }

  function drawFormat(m, size, mask) {
    var data = (0 << 3) | mask;          // ECC level M = 0b00
    var rem = data;
    for (var i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
    var bits = ((data << 10) | rem) ^ 0x5412;
    for (var k = 0; k <= 5; k++) m[k][8] = ((bits >>> k) & 1) === 1;
    m[7][8] = ((bits >>> 6) & 1) === 1;
    m[8][8] = ((bits >>> 7) & 1) === 1;
    m[8][7] = ((bits >>> 8) & 1) === 1;
    for (var j = 9; j < 15; j++) m[8][14 - j] = ((bits >>> j) & 1) === 1;
    for (var a = 0; a < 8; a++) m[8][size - 1 - a] = ((bits >>> a) & 1) === 1;
    for (var b = 8; b < 15; b++) m[size - 15 + b][8] = ((bits >>> b) & 1) === 1;
    m[size - 8][8] = true;
  }

  function penalty(m, size) {
    var p = 0, x, y, i;
    // rule 1: runs of 5+
    for (y = 0; y < size; y++) {
      var run = 1;
      for (x = 1; x < size; x++) {
        if (m[y][x] === m[y][x - 1]) { run++; if (run === 5) p += 3; else if (run > 5) p++; }
        else run = 1;
      }
    }
    for (x = 0; x < size; x++) {
      var runv = 1;
      for (y = 1; y < size; y++) {
        if (m[y][x] === m[y - 1][x]) { runv++; if (runv === 5) p += 3; else if (runv > 5) p++; }
        else runv = 1;
      }
    }
    // rule 2: 2x2 blocks
    for (y = 0; y < size - 1; y++)
      for (x = 0; x < size - 1; x++)
        if (m[y][x] === m[y][x + 1] && m[y][x] === m[y + 1][x] && m[y][x] === m[y + 1][x + 1]) p += 3;
    // rule 3: finder-like patterns
    var pat1 = [true, false, true, true, true, false, true, false, false, false, false];
    var pat2 = [false, false, false, false, true, false, true, true, true, false, true];
    function match(get, len) {
      var c = 0;
      for (var s = 0; s + 11 <= len; s++) {
        var ok1 = true, ok2 = true;
        for (var k = 0; k < 11; k++) {
          var vv = get(s + k);
          if (vv !== pat1[k]) ok1 = false;
          if (vv !== pat2[k]) ok2 = false;
        }
        if (ok1) c++;
        if (ok2) c++;
      }
      return c;
    }
    for (y = 0; y < size; y++) p += 40 * match(function (k) { return m[y][k]; }, size);
    for (x = 0; x < size; x++) p += 40 * match(function (k) { return m[k][x]; }, size);
    // rule 4: dark ratio
    var dark = 0;
    for (y = 0; y < size; y++) for (x = 0; x < size; x++) if (m[y][x]) dark++;
    var pct = dark * 100 / (size * size);
    p += Math.floor(Math.abs(pct - 50) / 5) * 10;
    return p;
  }

  function encode(text) {
    var bytes = utf8Bytes(text);
    var ver = chooseVersion(bytes.length);
    var cw = buildCodewords(bytes, ver);
    var built = makeMatrix(ver, cw);
    var best = null, bestScore = Infinity;
    for (var mask = 0; mask < 8; mask++) {
      var cand = applyMask(built.m, built.reserved, built.size, mask);
      drawFormat(cand, built.size, mask);
      var s = penalty(cand, built.size);
      if (s < bestScore) { bestScore = s; best = cand; }
    }
    return { size: built.size, modules: best, version: ver };
  }

  // Render as an SVG path string (1 unit per module) plus a quiet zone.
  function svgPath(text, quiet) {
    quiet = quiet === undefined ? 2 : quiet;
    var q = encode(text), d = [];
    for (var y = 0; y < q.size; y++)
      for (var x = 0; x < q.size; x++)
        if (q.modules[y][x]) d.push('M' + (x + quiet) + ' ' + (y + quiet) + 'h1v1h-1z');
    return { d: d.join(''), extent: q.size + quiet * 2, version: q.version };
  }

  root.MiscQR = { encode: encode, svgPath: svgPath };
})(typeof module !== 'undefined' && module.exports ? module.exports : (typeof window !== 'undefined' ? window : this));


/* types: picture motif and hue (the labels come from the server) */
var KINDS = {
  competition:{lt:'Konkursai ir kvietimai teikti kūrinius',en:'Competitions & calls for works',
               shortLt:'Konkursas',shortEn:'Competition',hue:38, motif:'burst'},
  festival   :{lt:'Festivaliai',en:'Festivals',
               shortLt:'Festivalis',shortEn:'Festival',hue:318, motif:'waves'},
  academy    :{lt:'Akademijos ir dirbtuvės',en:'Academies & workshops',
               shortLt:'Akademija',shortEn:'Academy',hue:172, motif:'bands'},
  conference :{lt:'Konferencijos ir simpoziumai',en:'Conferences & symposia',
               shortLt:'Konferencija',shortEn:'Conference',hue:212, motif:'network'},
  residency  :{lt:'Rezidencijos',en:'Residencies',
               shortLt:'Rezidencija',shortEn:'Residency',hue:142, motif:'orbit'},
  mobility   :{lt:'Mobilumas ir finansavimas',en:'Mobility & funding',
               shortLt:'Mobilumas',shortEn:'Mobility',hue:22, motif:'field'}
};
var KIND_ORDER = ["competition", "festival", "academy", "conference", "residency", "mobility"];

/* ================================================================
   6) VIZUALŲ GENERATORIUS
   Kiekvienam kvietimui sukuriamas unikalus piešinys. Sėkla —
   pavadinimas + miestas + šalis, tad tas pats kvietimas visada
   atrodo vienodai, o skirtingi — skirtingai.
   ================================================================ */
function hashSeed(s){var h=1779033703^s.length;
  for(var i=0;i<s.length;i++){h=Math.imul(h^s.charCodeAt(i),3432918353);h=h<<13|h>>>19;}
  return function(){h=Math.imul(h^h>>>16,2246822507);h=Math.imul(h^h>>>13,3266489909);
    return((h^=h>>>16)>>>0)/4294967296;};}

function visualFor(call){
  var kind = KINDS[call.kind] || KINDS.competition;
  var seedStr = (call.titleEn||'')+'|'+(call.cityEn||'')+'|'+(call.countryEn||'')+'|'+call.kind+
                '|'+(call.descEn||'').slice(0,40);
  var r = hashSeed(seedStr);
  var W=400,H=820;
  /* atspalvis svyruoja apie tipo bazinę reikšmę — tipas atpažįstamas, bet kiekvienas kvietimas savitas */
  var hue = (kind.hue + Math.round((r()-0.5)*46) + 360) % 360;
  var hue2 = (hue + (r()<0.5?-22:22) + 360) % 360;
  var uid = 'v'+Math.floor(r()*1e9).toString(36);
  var sat = 52+Math.round(r()*22), lum = 54+Math.round(r()*16);
  var c1='hsl('+hue+' '+sat+'% '+lum+'%)', c2='hsl('+hue2+' '+(sat-8)+'% '+(lum-16)+'%)';
  var p=[];
  p.push('<defs><linearGradient id="'+uid+'" x1="'+r().toFixed(2)+'" y1="0" x2="'+r().toFixed(2)+'" y2="1">'+
         '<stop offset="0" stop-color="hsl('+hue+' 32% '+(12+Math.round(r()*8))+'%)"/>'+
         '<stop offset="1" stop-color="hsl('+hue2+' 40% 7%)"/></linearGradient>'+
         '<radialGradient id="'+uid+'a" cx="50%" cy="42%" r="62%">'+
         '<stop offset="0" stop-color="'+c1+'" stop-opacity="'+(0.10+r()*0.14).toFixed(2)+'"/>'+
         '<stop offset="1" stop-color="'+c1+'" stop-opacity="0"/></radialGradient></defs>');
  p.push('<rect width="'+W+'" height="'+H+'" fill="url(#'+uid+')"/>');
  p.push('<rect width="'+W+'" height="'+H+'" fill="url(#'+uid+'a)"/>');
  /* MISC firminės brūkšnelių eilutės — bendras visų vizualų vardiklis */
  var dashRows = 3+Math.floor(r()*4), dashTop = r()<0.5 ? 40 : H-260;
  for(var dr=0;dr<dashRows;dr++){
    var dy0 = dashTop + dr*(26+r()*16);
    p.push('<rect x="'+(20+r()*90).toFixed(1)+'" y="'+dy0.toFixed(1)+'" width="'+
      (40+r()*210).toFixed(1)+'" height="6" rx="3" fill="#fff" opacity="'+(0.07+r()*0.16).toFixed(2)+'"/>');
  }
  var cx=W*(0.34+r()*0.32), cy=H*(0.30+r()*0.28), i, j, n;

  if(kind.motif==='burst'){
    n=16+Math.floor(r()*22);
    var inner=14+r()*44, spread=(0.55+r()*0.45);
    for(i=0;i<n;i++){var a=(i/n)*Math.PI*2*spread + r()*0.3 + r()*6.28*(spread<1?1:0);
      var len=inner+50+r()*(150+r()*180);
      p.push('<line x1="'+(cx+Math.cos(a)*inner).toFixed(1)+'" y1="'+(cy+Math.sin(a)*inner).toFixed(1)+
             '" x2="'+(cx+Math.cos(a)*len).toFixed(1)+
             '" y2="'+(cy+Math.sin(a)*len).toFixed(1)+'" stroke="'+(i%3?c1:c2)+
             '" stroke-width="'+(1.5+r()*8).toFixed(1)+'" opacity="'+(0.22+r()*0.55).toFixed(2)+'"/>');}
    var rings=1+Math.floor(r()*3);
    for(i=0;i<rings;i++)
      p.push('<circle cx="'+cx.toFixed(1)+'" cy="'+cy.toFixed(1)+'" r="'+(inner+30+i*(24+r()*40)).toFixed(1)+
             '" fill="none" stroke="'+c1+'" stroke-width="'+(1+r()*3).toFixed(1)+
             '" opacity="'+(0.18+r()*0.3).toFixed(2)+'"/>');
    p.push('<circle cx="'+cx.toFixed(1)+'" cy="'+cy.toFixed(1)+'" r="'+(inner*0.8).toFixed(1)+
           '" fill="'+c1+'" opacity=".92"/>');
  } else if(kind.motif==='waves'){
    n=13+Math.floor(r()*9);
    for(i=0;i<n;i++){var y=H*0.14+i*(H*0.72/n), amp=16+r()*54, d='M0 '+y.toFixed(1);
      for(j=1;j<=8;j++){var x=W*j/8, yy=y+Math.sin(j*1.1+i*0.7+r())*amp;
        d+=' Q'+(x-W/16).toFixed(1)+' '+yy.toFixed(1)+' '+x.toFixed(1)+' '+(y+Math.sin(j+i)*amp*0.5).toFixed(1);}
      p.push('<path d="'+d+'" fill="none" stroke="'+(i%3?c1:c2)+'" stroke-width="'+
             (1.6+r()*5).toFixed(1)+'" opacity="'+(0.22+r()*0.55).toFixed(2)+'"/>');}
  } else if(kind.motif==='bands'){
    var R=98+r()*54;
    p.push('<clipPath id="'+uid+'c"><circle cx="'+cx.toFixed(1)+'" cy="'+cy.toFixed(1)+'" r="'+R.toFixed(1)+'"/></clipPath>');
    p.push('<circle cx="'+cx.toFixed(1)+'" cy="'+cy.toFixed(1)+'" r="'+R.toFixed(1)+'" fill="'+c1+'" opacity=".92"/>');
    n=6+Math.floor(r()*8);
    for(i=0;i<n;i++){var by=cy-R+ i*(2*R/n)+ (r()*7);
      p.push('<rect clip-path="url(#'+uid+'c)" x="'+(cx-R).toFixed(1)+'" y="'+by.toFixed(1)+'" width="'+(2*R).toFixed(1)+
             '" height="'+(4+r()*13).toFixed(1)+'" fill="hsl('+hue+' 34% 11%)" opacity=".88"/>');}
    var rows=5+Math.floor(r()*5);
    for(i=0;i<rows;i++){var ly=cy+R+34+i*(26+r()*18);
      p.push('<rect x="'+(cx-(20+r()*150)).toFixed(1)+'" y="'+ly.toFixed(1)+'" width="'+
             (50+r()*230).toFixed(1)+'" height="7" rx="3.5" fill="'+c2+'" opacity="'+(0.28+r()*0.5).toFixed(2)+'"/>');}
  } else if(kind.motif==='network'){
    var pts=[], m=13+Math.floor(r()*10);
    for(i=0;i<m;i++)pts.push([40+r()*(W-80), 60+r()*(H-120)]);
    for(i=0;i<pts.length;i++)for(j=i+1;j<pts.length;j++){
      var dx=pts[i][0]-pts[j][0], dy=pts[i][1]-pts[j][1], dist=Math.sqrt(dx*dx+dy*dy);
      if(dist<175)p.push('<line x1="'+pts[i][0].toFixed(1)+'" y1="'+pts[i][1].toFixed(1)+'" x2="'+
        pts[j][0].toFixed(1)+'" y2="'+pts[j][1].toFixed(1)+'" stroke="'+c1+
        '" stroke-width="1.6" opacity="'+(0.5-dist/420).toFixed(2)+'"/>');}
    for(i=0;i<pts.length;i++)p.push('<circle cx="'+pts[i][0].toFixed(1)+'" cy="'+pts[i][1].toFixed(1)+
      '" r="'+(4+r()*11).toFixed(1)+'" fill="'+(i%4?c1:c2)+'" opacity="'+(0.55+r()*0.4).toFixed(2)+'"/>');
  } else if(kind.motif==='orbit'){
    n=6+Math.floor(r()*8);
    var baseAng=r()*180, tilt=0.24+r()*0.6;
    for(i=0;i<n;i++){var rr=30+i*(190/n)+r()*26, ang=baseAng+(r()-0.5)*46;
      p.push('<ellipse cx="'+(cx+(r()-0.5)*46).toFixed(1)+'" cy="'+(cy+(r()-0.5)*46).toFixed(1)+
        '" rx="'+rr.toFixed(1)+'" ry="'+(rr*tilt).toFixed(1)+'" transform="rotate('+
        ang.toFixed(1)+' '+cx.toFixed(1)+' '+cy.toFixed(1)+')" fill="none" stroke="'+(i%2?c1:c2)+
        '" stroke-width="'+(1.6+r()*4.5).toFixed(1)+'" opacity="'+(0.28+r()*0.5).toFixed(2)+'"/>');}
    for(i=0;i<3+Math.floor(r()*4);i++){var oa=r()*6.28, orr=50+r()*180;
      p.push('<circle cx="'+(cx+Math.cos(oa)*orr).toFixed(1)+'" cy="'+(cy+Math.sin(oa)*orr*tilt).toFixed(1)+
        '" r="'+(3+r()*9).toFixed(1)+'" fill="'+c1+'" opacity=".8"/>');}
    p.push('<circle cx="'+cx.toFixed(1)+'" cy="'+cy.toFixed(1)+'" r="'+(13+r()*18).toFixed(1)+'" fill="#fff" opacity=".85"/>');
  } else { /* field */
    n=100+Math.floor(r()*70);
    for(i=0;i<n;i++){var fx=r()*W, fy=r()*H, s=1.5+r()*7;
      p.push('<circle cx="'+fx.toFixed(1)+'" cy="'+fy.toFixed(1)+'" r="'+s.toFixed(1)+
             '" fill="'+(i%5?c1:c2)+'" opacity="'+(0.15+r()*0.6).toFixed(2)+'"/>');}
    for(i=0;i<5;i++){var ay=120+i*140+r()*40;
      p.push('<path d="M30 '+ay.toFixed(1)+' Q'+(W/2)+' '+(ay-70-r()*60).toFixed(1)+' '+(W-30)+' '+
             ay.toFixed(1)+'" fill="none" stroke="'+c2+'" stroke-width="'+(2+r()*4).toFixed(1)+
             '" opacity="'+(0.3+r()*0.4).toFixed(2)+'"/>');}
  }
  /* šalies kodas fone */
  var cc=(call.countryCode||'').toUpperCase();
  if(cc)p.push('<text x="'+(W-26)+'" y="'+(H-104)+'" text-anchor="end" font-size="132" font-weight="700"'+
    ' fill="#fff" opacity=".09" font-family="inherit">'+esc(cc)+'</text>');
  return '<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="xMidYMid slice">'+p.join('')+'</svg>';
}

/* ================================================================
   7) ATVAIZDAVIMAS
   ================================================================ */
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
  return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}

function hostOf(u){
  try{return String(u).replace(/^https?:\/\//,'').replace(/^www\./,'').split('/')[0];}
  catch(e){return '';}
}

function qrSvg(url){
  try{
    var q = MiscQR.svgPath(url, 3);
    return '<svg viewBox="0 0 '+q.extent+' '+q.extent+'" shape-rendering="crispEdges">'+
           '<rect width="'+q.extent+'" height="'+q.extent+'" fill="#fff"/>'+
           '<path d="'+q.d+'" fill="#000"/></svg>';
  }catch(e){
    return '<svg viewBox="0 0 10 10"><rect width="10" height="10" fill="#fff"/>'+
           '<text x="5" y="5.6" font-size="1.6" text-anchor="middle" fill="#900">QR?</text></svg>';
  }
}

var MONTH_LT=['sausio','vasario','kovo','balandžio','gegužės','birželio','liepos',
              'rugpjūčio','rugsėjo','spalio','lapkričio','gruodžio'];
var MONTH_EN=['January','February','March','April','May','June','July',
              'August','September','October','November','December'];
function fmtDeadline(c){
  if(!c.deadline) return {big:'', wordLt:c.deadlineWordLt||'', wordEn:c.deadlineWordEn||''};
  var p=c.deadline.split('-'), y=+p[0], m=+p[1], d=+p[2];
  return {big:true, day:String(d),
          monLt:MONTH_LT[m-1]+' '+y,
          monEn:MONTH_EN[m-1]+' '+y,
          wordLt:y+' m. '+MONTH_LT[m-1]+' '+d+' d.',
          wordEn:d+' '+MONTH_EN[m-1]+' '+y};
}


/* kiek dienų iki termino — naudojama TIK „skubu“ žymai, skaičius nerodomas */
function daysLeft(c){
  if(!c.deadline) return null;
  var p=c.deadline.split('-');
  var d=new Date(Date.UTC(+p[0],+p[1]-1,+p[2]));
  var now=CONFIG.today?new Date(CONFIG.today+'T00:00:00Z'):new Date();
  return Math.round((d-Date.UTC(now.getUTCFullYear(),now.getUTCMonth(),now.getUTCDate()))/864e5);
}

/* ================================================================
   8) FIELDS, SERIES, CARDS
   ================================================================ */
function fieldOf(key){
  for(var i=0;i<FIELDS.length;i++) if(FIELDS[i].key===key) return FIELDS[i];
  return {key:key, lt:key||'', en:key||'', hue:220, n:0};
}
function fieldColor(f){ return 'hsl('+(f && f.hue!=null ? f.hue : 220)+' 60% 52%)'; }

/* 1 kvietimas · 2 kvietimai · 10 kvietimų · 21 kvietimas */
function ltCalls(n){
  var d=n%10, dd=n%100;
  if(d===1 && dd!==11) return n+' kvietimas';
  if(d>=2 && (dd<10 || dd>=20)) return n+' kvietimai';
  return n+' kvietimų';
}

var SERIES_ICON='<svg class="sico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '+
  'stroke-linecap="round" stroke-linejoin="round"><path d="M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3"/>'+
  '<path d="M18 3v4h-4M6 21v-4h4"/></svg>';

function topicsHtml(c){
  var list=(c.topics||[]).map(function(t){
    return '<span class="topic ctx">'+esc(t.lt)+
      (t.en && t.en!==t.lt ? '<span class="en">'+esc(t.en)+'</span>' : '')+'</span>';
  }).join('');
  return list ? '<div class="topics">'+list+'</div>' : '';
}

function placeHtml(city, country){
  return [city, country].filter(Boolean).map(esc).join(', ');
}

function cardHtml(c){
  var k=KINDS[c.kind]||KINDS.competition, dl=fmtDeadline(c), s=c.series;
  var kindStyle='background:hsl('+k.hue+' 55% 20%);color:hsl('+k.hue+' 75% 74%)';
  var dleft=daysLeft(c);
  var urgent=CONFIG.markUrgent && dleft!==null && dleft>=0 && dleft<=CONFIG.urgentDays;
  var pLt=placeHtml(c.cityLt, c.countryLt), pEn=placeHtml(c.cityEn, c.countryEn);
  var descMain=c.descLt||c.descEn, descEn=(c.descLt && c.descEn && c.descEn!==c.descLt) ? c.descEn : '';
  return '<div class="card'+(urgent?' urgent':'')+(s?' series':'')+'">'+
    '<div class="vis">'+visualFor(c)+
      '<div class="visLabel">'+esc(c.cityEn||c.countryEn||'')+'</div></div>'+
    '<div class="body">'+
      '<span class="kind" style="'+kindStyle+'">'+esc(c.kindLt)+
        (c.kindEn && c.kindEn!==c.kindLt ? ' · '+esc(c.kindEn) : '')+'</span>'+
      (s ? '<div class="serline">'+SERIES_ICON+'<b>'+esc(s.lt)+'</b>'+
           '<span>Serija · Series'+(s.n>1 ? ' · '+ltCalls(s.n)+' / '+s.n+' calls' : '')+'</span></div>' : '')+
      '<h2>'+esc(c.titleLt)+'</h2>'+
      (c.titleEn && c.titleEn!==c.titleLt ? '<div class="titleEn">'+esc(c.titleEn)+'</div>' : '')+
      (pLt ? '<div class="place">'+pLt+(pEn && pEn!==pLt ? '<div class="placeEn">'+pEn+'</div>' : '')+'</div>' : '')+
      topicsHtml(c)+
      (descMain ? '<div class="desc">'+esc(descMain)+(descEn ? '<div class="descEn">'+esc(descEn)+'</div>' : '')+'</div>' : '')+
      '<div class="spacer"></div>'+
    '</div>'+
    '<div class="side">'+
      (s && s.n>1 ? '<div class="dlLabel">Artimiausias terminas</div><div class="dlLabelEn">Next deadline</div>'
                  : '<div class="dlLabel">Terminas</div><div class="dlLabelEn">Deadline</div>')+
      (dl.big?'<div class="dlDay">'+esc(dl.day)+'</div>'+
              '<div class="dlMon">'+esc(dl.monLt)+'</div>'+
              '<div class="dlMonEn">'+esc(dl.monEn)+'</div>'
             :'<div class="dlWord">'+esc(dl.wordLt||'Nuolat')+'<br><span style="color:#9aa6bd;font-weight:400">'+
              esc(dl.wordEn||'Rolling')+'</span></div>')+
      (urgent?'<div class="soon">Skubu<span>Closing soon</span></div>':'')+
      '<div class="qrBox">'+qrSvg(c.url)+'</div>'+
      (s ? '<div class="scan"><b>Skenuok</b>All calls of the series</div>'
         : '<div class="scan"><b>Skenuok</b>Scan for details</div>')+
      '<div class="host">'+esc(hostOf(c.url))+'</div>'+
    '</div>'+
  '</div>';
}

function fillerHtml(){
  return '<div class="card filler">'+MISC_LOGO+
    '<div class="ftxt"><b>Daugiau kvietimų</b>More open calls<br>'+esc(CONFIG.siteLabel||'misc.lmta.lt')+'</div></div>';
}

function coverHtml(){
  var lg=FIELDS.map(function(f){
    return '<div class="lg"><i class="sw" style="background:'+fieldColor(f)+'"></i>'+
      '<div class="lgt">'+esc(f.lt)+'<span>'+esc(f.en)+(f.n ? ' · '+f.n : '')+'</span></div></div>';
  }).join('');
  return '<div class="cmain">'+MISC_LOGO.replace('class="logo"','class="logo clogo"')+
      '<h1>Atviri kvietimai studentams</h1>'+
      '<div class="h1en">Open calls for students</div>'+
      (CALLS.length ? '<div class="legendTitle">Sritys · Fields</div><div class="legend">'+lg+'</div>'
                    : '<div class="legendTitle">Šiuo metu atvirų kvietimų nėra · No open calls right now</div>')+
    '</div>'+
    '<div class="cqr"><div class="qrBox">'+qrSvg(CONFIG.searchUrlFull||location.href)+'</div>'+
      '<div class="scan"><b>Visi kvietimai ir paieška</b>All calls &amp; search</div>'+
      '<div class="host">'+esc(CONFIG.siteLabel||'')+'</div></div>';
}

/* pages: grouped by field (in the admin's order), by deadline inside, CONFIG.perPage per page */
function buildPages(){
  var pages=[], order=FIELDS.map(function(f){return f.key;});
  CALLS.forEach(function(c){ if(order.indexOf(c.field)<0) order.push(c.field); });
  order.forEach(function(fk){
    var list=CALLS.filter(function(c){return c.field===fk;});
    if(!list.length) return;
    list.sort(function(a,b){
      return (a.deadline||'9999').localeCompare(b.deadline||'9999') || String(a.titleLt).localeCompare(String(b.titleLt));
    });
    var parts=Math.ceil(list.length/CONFIG.perPage);
    for(var i=0;i<list.length;i+=CONFIG.perPage)
      pages.push({field:fk, items:list.slice(i,i+CONFIG.perPage), part:i/CONFIG.perPage+1, parts:parts});
  });
  if(CONFIG.showCover || !pages.length) pages.unshift({cover:true, items:[]});
  return pages;
}

var PAGES=buildPages(), idx=0, timer=null, tick=null, LOADED=Date.now();

function render(){
  if(!PAGES.length) return;
  var pg=PAGES[idx], f=pg.cover ? null : fieldOf(pg.field);
  document.getElementById('logoSlot').innerHTML=MISC_LOGO;
  var secLt=document.getElementById('sectionLt'), secEn=document.getElementById('sectionEn');
  if(pg.cover){
    secLt.textContent='LMTA · Muzikos inovacijų studijų centras';
    secEn.textContent='Music Innovation Studies Centre';
  }else{
    secLt.innerHTML='<i class="hdot" style="background:'+fieldColor(f)+'"></i>'+esc(f.lt);
    secEn.textContent=f.en+(pg.parts>1 ? '   ·   '+pg.part+' / '+pg.parts : '');
  }
  /* "Next" names the NEXT field only — not the same one continuing over several pages */
  var nf=null;
  for(var s=1;s<PAGES.length;s++){
    var cand=PAGES[(idx+s)%PAGES.length];
    if(cand.cover) continue;
    if(pg.cover || cand.field!==pg.field){ nf=fieldOf(cand.field); break; }
  }
  document.getElementById('nextUp').innerHTML=
    nf ? 'Toliau: '+esc(nf.lt)+' <span>· Next: '+esc(nf.en)+'</span>' : '';
  document.getElementById('dateLine').textContent=(CONFIG.updatedLt||'')+'  ·  '+(CONFIG.updatedEn||'');
  document.getElementById('footLeft').innerHTML=
    '<b>Sąrašas atnaujinamas kas savaitę — sekite naujienas</b>'+
    '<span class="en">&nbsp;&nbsp;·&nbsp;&nbsp;Updated every week — stay tuned</span>';
  document.getElementById('footRight').innerHTML=
    esc(CONFIG.siteLabel||'misc.lmta.lt')+'&nbsp;&nbsp;·&nbsp;&nbsp;<span class="en">Skenuokite QR kodą telefonu · Scan the QR code</span>';
  document.getElementById('prog').style.background = f ? fieldColor(f) : '#6b8cff';
  var g=document.getElementById('grid'), cv=document.getElementById('cover'), n=pg.items.length;
  if(pg.cover){
    g.style.display='none'; cv.className='on'; cv.innerHTML=coverHtml();
    cv.style.animation='none'; void cv.offsetWidth; cv.style.animation='';
    return;
  }
  cv.className=''; g.style.display='';
  g.className = n<4 ? ('n'+n) : '';
  g.innerHTML=pg.items.map(cardHtml).join('');
  g.style.animation='none'; void g.offsetWidth; g.style.animation='';
}

/* after a full round, and at most every CONFIG.reloadMinutes, fetch fresh data — only if the server answers */
function maybeReload(){
  if(!CONFIG.reloadMinutes || Date.now()-LOADED < CONFIG.reloadMinutes*60000) return false;
  LOADED=Date.now();
  fetch(location.href, {method:'HEAD', cache:'no-store'})
    .then(function(r){ if(r.ok) location.reload(); })
    .catch(function(){ /* offline: keep showing what we have */ });
  return true;
}

function go(d){
  idx=(idx+d+PAGES.length)%PAGES.length;
  if(idx===0 && d>0) maybeReload();
  render(); restart();
}
function restart(){
  clearInterval(timer); clearInterval(tick);
  var bar=document.getElementById('prog'); bar.style.width='0%';
  if(!CONFIG.autoplay || PAGES.length<2) return;
  var t0=Date.now(), ms=CONFIG.slideSeconds*1000;
  tick=setInterval(function(){bar.style.width=Math.min(100,(Date.now()-t0)/ms*100)+'%';},240);
  timer=setInterval(function(){go(1);},ms);
}

/* ================================================================
   9) FILL THE SCREEN
   The design is drawn in units of a 3840×2160 screen. The canvas grows in one direction to
   match the window's shape (16:10 laptop → taller, ultrawide → wider), then is zoomed to fit:
   no black bars, and the browser renders text and vector pictures at the screen's own resolution.
   ================================================================ */
var USE_ZOOM = !!(window.CSS && CSS.supports && CSS.supports('zoom', '0.5'));
function fit(){
  var W=window.innerWidth, H=window.innerHeight, s=Math.min(W/3840, H/2160);
  var st=document.getElementById('stage');
  st.style.width=(W/s)+'px'; st.style.height=(H/s)+'px';
  if(USE_ZOOM) st.style.zoom=s; else st.style.transform='scale('+s+')';
}

/* ---- fullscreen, search link, pause: a small panel that shows only while the mouse moves ---- */
function isFull(){
  return !!(document.fullscreenElement || document.webkitFullscreenElement) ||
         (window.innerWidth>=screen.width && window.innerHeight>=screen.height);   /* kiosk mode */
}
function toggleFull(){
  var el=document.documentElement;
  if(document.fullscreenElement || document.webkitFullscreenElement){
    (document.exitFullscreen||document.webkitExitFullscreen).call(document);
  }else{
    var req=el.requestFullscreen||el.webkitRequestFullscreen;
    if(req){ var p=req.call(el); if(p && p.catch) p.catch(function(){}); }
  }
}
var ctl=document.getElementById('ctl'), idleT=null;
function updateCtl(){
  document.getElementById('ctlFs').querySelector('span').textContent =
    (document.fullscreenElement||document.webkitFullscreenElement) ? 'Išeiti · Exit' : 'Visas ekranas · Fullscreen';
  document.getElementById('ctlPlay').textContent = CONFIG.autoplay ? '❚❚' : '▶';
  document.getElementById('ctlPlay').title = CONFIG.autoplay ? 'Pauzė · Pause (P)' : 'Groti · Play (P)';
}
function wake(){
  document.body.classList.remove('idle'); ctl.classList.add('on');
  clearTimeout(idleT);
  idleT=setTimeout(function(){ ctl.classList.remove('on'); document.body.classList.add('idle'); }, 3000);
}
document.getElementById('ctlFs').addEventListener('click', function(){ toggleFull(); });
document.getElementById('ctlPlay').addEventListener('click', function(){
  CONFIG.autoplay=!CONFIG.autoplay; restart(); updateCtl();
});
document.addEventListener('fullscreenchange', function(){ updateCtl(); fit(); });
document.addEventListener('webkitfullscreenchange', function(){ updateCtl(); fit(); });
['mousemove','touchstart'].forEach(function(ev){ document.addEventListener(ev, wake, {passive:true}); });

window.addEventListener('resize', fit);
document.addEventListener('keydown', function(e){
  if(e.ctrlKey || e.metaKey || e.altKey) return;
  var k=e.key.toLowerCase();
  if(e.key==='ArrowRight'||e.key===' ') { e.preventDefault(); go(1); }
  else if(e.key==='ArrowLeft') go(-1);
  else if(k==='p'){ CONFIG.autoplay=!CONFIG.autoplay; restart(); updateCtl(); }
  else if(k==='f') toggleFull();
  else if(k==='s') location.href=CONFIG.searchUrl;
});
document.addEventListener('click', function(e){
  if(e.target.closest && e.target.closest('#ctl')) return;
  go(1);
});
fit(); render(); restart(); updateCtl();
if(!isFull()) wake(); else document.body.classList.add('idle');
