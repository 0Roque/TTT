"use strict";
/* Landing page: check the code and open the tournament page. Display only: nothing is ever sent or stored. */
const CODE_RE = /^[a-z0-9]{32}$/;
const inp = document.getElementById("code"), err = document.getElementById("err"), count = document.getElementById("count");
inp.addEventListener("input", () => { inp.value = inp.value.toLowerCase().replace(/[^a-z0-9]/g, ""); count.textContent = `${inp.value.length} / 32`; err.textContent = ""; });
document.getElementById("f").addEventListener("submit", async e => {
  e.preventDefault();
  const code = inp.value.trim().toLowerCase();
  if(!CODE_RE.test(code)){ err.textContent = "A tournament code is exactly 32 letters (a–z) and digits."; return; }
  try{
    const r = await fetch(`${await Vault.fileUrl(code)}?v=${Date.now()}`, {method:"HEAD", cache:"no-store"});
    if(r.status === 404){ err.textContent = "No tournament found with this code."; return; }
  }catch(_){ /* network hiccup: let the tournament page report it */ }
  location.href = `tournament.html#${code}`;
});
const q = location.hash.slice(1);
if(q){ inp.value = q; inp.dispatchEvent(new Event("input")); }
inp.focus();
