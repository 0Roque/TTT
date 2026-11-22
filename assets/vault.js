"use strict";
/* Loads an encrypted tournament file. Mirrors tools/ttt.py:
   id/keys = HMAC-SHA256(code, label); content = AES-256-CBC, authenticated with HMAC-SHA256(iv || ct). */
const Vault = (() => {
  const enc = new TextEncoder();
  const hex = b => [...b].map(x => x.toString(16).padStart(2, "0")).join("");
  const unb64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
  async function derive(code, label){
    const k = await crypto.subtle.importKey("raw", enc.encode(code), {name:"HMAC", hash:"SHA-256"}, false, ["sign"]);
    return new Uint8Array(await crypto.subtle.sign("HMAC", k, enc.encode(label)));
  }
  const fileUrl = async code => `data/${hex(await derive(code, "ttt-file"))}.json`;
  async function load(code){
    if(!window.crypto || !crypto.subtle) throw new Error("this browser cannot decrypt (page must be served over https)");
    const r = await fetch(`${await fileUrl(code)}?v=${Date.now()}`, {cache:"no-store"});
    if(r.status === 404) return null;
    if(!r.ok) throw new Error(`HTTP ${r.status}`);
    const box = await r.json(), iv = unb64(box.iv), ct = unb64(box.ct), tag = unb64(box.tag);
    const mk = await crypto.subtle.importKey("raw", await derive(code, "ttt-mac"), {name:"HMAC", hash:"SHA-256"}, false, ["verify"]);
    const signed = new Uint8Array(iv.length + ct.length); signed.set(iv); signed.set(ct, iv.length);
    if(!await crypto.subtle.verify("HMAC", mk, tag, signed)) throw new Error("the file failed its integrity check");
    const ek = await crypto.subtle.importKey("raw", await derive(code, "ttt-enc"), {name:"AES-CBC"}, false, ["decrypt"]);
    return JSON.parse(new TextDecoder().decode(await crypto.subtle.decrypt({name:"AES-CBC", iv}, ek, ct)));
  }
  return {fileUrl, load};
})();
