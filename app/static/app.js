// Ingen inline-JS – CSP tillåter bara script från samma origin.
"use strict";

document.addEventListener("submit", (e) => {
  const msg = e.target.getAttribute("data-confirm") ||
              (e.submitter && e.submitter.getAttribute("data-confirm"));
  if (msg && !window.confirm(msg)) { e.preventDefault(); return; }
  if (e.target.hasAttribute("data-upload")) {
    const st = e.target.querySelector("[data-upload-status]");
    if (st) st.hidden = false;
    const btn = e.target.querySelector("button");
    if (btn) { btn.disabled = true; btn.textContent = "Laddar upp …"; }
  }
});

document.addEventListener("click", async (e) => {
  const copyBtn = e.target.closest("[data-copy]");
  if (copyBtn) {
    const input = document.getElementById(copyBtn.getAttribute("data-copy"));
    if (!input) return;
    try { await navigator.clipboard.writeText(input.value); }
    catch { input.select(); document.execCommand("copy"); }
    const old = copyBtn.textContent; copyBtn.textContent = "Kopierad ✓";
    setTimeout(() => (copyBtn.textContent = old), 1500);
    return;
  }
  if (e.target.closest("[data-print]")) { e.preventDefault(); window.print(); }
});

// Uppdatera sidan medan e-postutskick pågår
const refresh = document.querySelector("[data-autorefresh]");
if (refresh) {
  const again = () => (document.querySelector("[data-timer]:not([hidden])") ? setTimeout(again, 10000) : location.reload());
  setTimeout(again, Number(refresh.dataset.autorefresh) * 1000);  // ladda inte om mitt i ett tal
}

// Visa valda filnamn vid uppladdning
document.querySelectorAll(".upload-drop input[type=file]").forEach((inp) => {
  inp.addEventListener("change", () => {
    const n = inp.files.length;
    inp.nextElementSibling.textContent = n ? `${n} ${n === 1 ? "bild vald" : "bilder valda"}` : "Välj bilder";
  });
});

// ------------------------------------------------------------------ bordsplacering
const board = document.querySelector(".seating.editable");
if (board) {
  const csrf = board.dataset.csrf;
  let selected = null;

  const recount = () => {
    board.querySelectorAll("[data-table]").forEach((t) => {
      const used = [...t.querySelectorAll(".chip-guest")].reduce((s, c) => s + Number(c.dataset.need), 0);
      const out = t.querySelector("[data-used]");
      if (out) out.textContent = used;
      if (t.dataset.seats) t.classList.toggle("over", used > Number(t.dataset.seats));
    });
  };

  const move = async (chip, tableEl) => {
    const from = chip.parentElement;
    const tableId = tableEl.dataset.table || null;
    if (chip.closest("[data-table]") === tableEl) return;
    tableEl.querySelector(".drop").appendChild(chip);
    recount();
    try {
      const r = await fetch("/seating/assign", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({ guest_id: Number(chip.dataset.guest), table_id: tableId ? Number(tableId) : null }),
      });
      if (!r.ok) throw new Error(r.status);
    } catch (err) {
      from.appendChild(chip); recount();
      alert("Kunde inte spara placeringen. Ladda om sidan och försök igen.");
    }
  };

  const clearSel = () => { if (selected) selected.classList.remove("selected"); selected = null;
                           board.classList.remove("picking"); };

  board.addEventListener("dragstart", (e) => {
    const chip = e.target.closest(".chip-guest");
    if (!chip) return;
    e.dataTransfer.setData("text/plain", chip.dataset.guest);
    e.dataTransfer.effectAllowed = "move";
    chip.classList.add("dragging");
  });
  board.addEventListener("dragend", (e) => {
    const chip = e.target.closest(".chip-guest");
    if (chip) chip.classList.remove("dragging");
    board.querySelectorAll(".dragover").forEach((x) => x.classList.remove("dragover"));
  });
  board.addEventListener("dragover", (e) => {
    const t = e.target.closest("[data-table]");
    if (!t) return;
    e.preventDefault();
    board.querySelectorAll(".dragover").forEach((x) => x !== t && x.classList.remove("dragover"));
    t.classList.add("dragover");
  });
  board.addEventListener("drop", (e) => {
    const t = e.target.closest("[data-table]");
    if (!t) return;
    e.preventDefault();
    t.classList.remove("dragover");
    const chip = board.querySelector(`.chip-guest[data-guest="${CSS.escape(e.dataTransfer.getData("text/plain"))}"]`);
    if (chip) move(chip, t);
  });

  // Tryck-läge (mobil/tangentbord): välj hushåll, välj sedan bord
  board.addEventListener("click", (e) => {
    if (e.target.closest("a")) return;
    const chip = e.target.closest(".chip-guest");
    if (chip) {
      if (selected === chip) { clearSel(); return; }
      clearSel(); selected = chip; chip.classList.add("selected"); board.classList.add("picking");
      return;
    }
    const t = e.target.closest("[data-table]");
    if (t && selected) { const c = selected; clearSel(); move(c, t); }
  });
  board.addEventListener("keydown", (e) => {
    if (e.key === "Escape") clearSel();
    if ((e.key === "Enter" || e.key === " ") && e.target.matches(".chip-guest, [data-table]")) {
      e.preventDefault(); e.target.click();
    }
  });
}

// Gästformulär: när OSA sätts till "Kommer" och antal saknas → fyll i antal inbjudna
const rsvpSel = document.querySelector('select[name="rsvp"]');
const attIn = document.querySelector('input[name="attending"]');
const invIn = document.querySelector('input[name="invited_count"]');
if (rsvpSel && attIn && invIn) {
  rsvpSel.addEventListener("change", () => {
    if (rsvpSel.value === "yes" && (!attIn.value || attIn.value === "0")) attIn.value = invIn.value || "1";
    if (rsvpSel.value === "no") attIn.value = "0";
  });
}

// OSA-kort: förhandsvisa texten under koden medan man skriver (textContent → aldrig HTML)
const footerForm = document.querySelector(".footer-editor");
if (footerForm) {
  const input = footerForm.querySelector("[data-footer-input]");
  const counter = footerForm.querySelector("[data-footer-count]");
  let vars = {};
  try { vars = JSON.parse(footerForm.dataset.vars || "{}"); } catch { vars = {}; }
  const render = () => {
    const tpl = input.value;
    document.querySelectorAll(".osa-footer").forEach((el) => {
      const v = { ...vars, namn: el.dataset.namn || "", antal: el.dataset.antal || "" };
      const text = tpl.replace(/\{(osa_senast|namn|antal|datum|brudpar|plats)\}/g, (_, k) => v[k] ?? "");
      el.textContent = text.trim();
      el.hidden = !text.trim();
    });
    if (counter) counter.textContent = `(${input.value.length}/${input.maxLength})`;
  };
  input.addEventListener("input", render);
  footerForm.querySelector("[data-footer-reset]")?.addEventListener("click", (e) => {
    input.value = e.currentTarget.dataset.footerReset; render(); input.focus();
  });
  render();
}

// OSA: dölj personraderna när gästen svarar "Tyvärr inte"
const peopleBox = document.querySelector("[data-people]");
if (peopleBox) {
  const answers = document.querySelectorAll('input[name="answer"]');
  const update = () => {
    const no = document.querySelector('input[name="answer"][value="no"]');
    document.querySelectorAll("[data-people], [data-yes-only]").forEach((el) => el.toggleAttribute("data-hidden", Boolean(no && no.checked)));
  };
  answers.forEach((r) => r.addEventListener("change", update));
  update();
}

// Bildspel: växlar bild var n:e sekund och hämtar nya bilder var 30:e sekund (nya visas först)
const show = document.querySelector("[data-slideshow]");
if (show) {
  const imgs = show.querySelectorAll(".show-img");
  const empty = show.querySelector("[data-show-empty]");
  const seconds = Number(show.dataset.interval) || 8;
  let photos = [], queue = [], seen = null, front = 0, pos = 0;

  const load = async () => {
    try {
      const r = await fetch("/photos/bildspel.json", { credentials: "same-origin" });
      if (!r.ok) return;
      const data = await r.json();
      photos = data.photos;  // nyast först
      greetings = data.greetings || [];
      if (seen) {  // bilder som tillkommit sedan förra hämtningen visas härnäst, äldst först
        queue.push(...photos.filter((p) => !seen.has(p.id)).reverse());
      }
      seen = new Set(photos.map((p) => p.id));
      empty.hidden = photos.length > 0 || greetings.length > 0;
    } catch { /* nätverksfel: försök igen nästa gång */ }
  };

  let greetings = [], gpos = 0, tick = 0;
  const greetBox = show.querySelector("[data-show-greeting]");
  const next = () => {
    tick += 1;
    // var fjärde gång: en hälsning ur gästboken ovanpå bilden
    if (greetBox && greetings.length && (tick % 4 === 0 || !photos.length)) {
      const g = greetings[gpos++ % greetings.length];
      greetBox.querySelector("[data-greeting-text]").textContent = g.text;
      greetBox.querySelector("[data-greeting-name]").textContent = g.name ? "– " + g.name : "";
      greetBox.hidden = false; empty.hidden = true;
      return;
    }
    if (greetBox) greetBox.hidden = true;
    if (!photos.length) return;
    const p = queue.shift() || photos[pos++ % photos.length];
    const img = imgs[1 - front];
    const caption = show.querySelector("[data-show-caption]");
    img.onload = () => {
      img.classList.add("on"); imgs[front].classList.remove("on"); front = 1 - front;
      if (caption) { caption.textContent = p.caption ? "🎯 " + p.caption : ""; caption.hidden = !p.caption; }
    };
    img.src = p.src;
  };

  show.addEventListener("click", (e) => {
    if (e.target.closest("a")) return;
    if (document.fullscreenElement) document.exitFullscreen();
    else show.requestFullscreen?.().catch(() => {});
  });

  load().then(next);
  setInterval(next, seconds * 1000);
  setInterval(load, 30000);
}

// Trycksaker: förhandsvisa medan man skriver. Platshållare fylls i med exempelvärden; textContent → aldrig HTML.
const cardEditor = document.querySelector("[data-card-editor]");
const cardPreview = document.querySelector("[data-card-preview]");
if (cardEditor && cardPreview) {
  let vars = {};
  try { vars = JSON.parse(cardPreview.closest("[data-vars]").dataset.vars || "{}"); } catch { vars = {}; }
  const fill = (tpl) => tpl.replace(/\{([a-zåäö_]+)\}/g, (m, k) => (k in vars ? vars[k] : m));
  const picker = document.querySelector("[data-design-picker]");
  const thumbs = picker ? [...picker.querySelectorAll(".pcard")] : [];
  const setClass = (el, prefix, value) => {
    [...el.classList].filter((c) => c.startsWith(prefix)).forEach((c) => el.classList.remove(c));
    el.classList.add(prefix + value);
  };
  const update = () => {
    cardEditor.querySelectorAll("[data-text]").forEach((inp) => {
      const text = fill(inp.value).trim();
      [cardPreview, ...thumbs].forEach((card) => {
        const out = card.querySelector(`[data-f="${inp.dataset.text}"]`);
        if (out) out.textContent = text;
      });
    });
    cardEditor.querySelectorAll("select[data-class-prefix]").forEach((sel) => {
      const prefix = sel.dataset.classPrefix;
      setClass(cardPreview, prefix, sel.value);
      if (prefix !== "d-") thumbs.forEach((t) => setClass(t, prefix, sel.value));  // miniatyrerna behåller sin design
      if (prefix === "d-" && picker) {
        picker.querySelectorAll("[data-pick-design]").forEach((b) =>
          b.setAttribute("aria-pressed", String(b.dataset.pickDesign === sel.value)));
      }
    });
    const qrBox = cardPreview.querySelector("[data-qr]");
    const qrToggle = cardEditor.querySelector("[data-qr-toggle]");
    if (qrBox && qrToggle) qrBox.hidden = !qrToggle.checked || !qrBox.firstElementChild;
    const qrOptions = cardEditor.querySelector("[data-qr-options]");
    if (qrOptions && qrToggle) qrOptions.hidden = !qrToggle.checked;
  };
  cardEditor.addEventListener("input", update);
  cardEditor.addEventListener("change", update);

  // QR-stil: hämta en exempelkod i vald stil från servern (vår egen SVG, samma origin)
  let qrReq = 0;
  cardEditor.addEventListener("change", async (e) => {
    if (!e.target.matches("[data-qr-param]")) return;
    const params = new URLSearchParams();
    cardEditor.querySelectorAll("[data-qr-param]").forEach((s) => params.set(s.dataset.qrParam, s.value));
    const mine = ++qrReq;
    try {
      const r = await fetch("/kort/qr.svg?" + params, { credentials: "same-origin" });
      if (!r.ok || mine !== qrReq) return;
      const svg = new DOMParser().parseFromString(await r.text(), "image/svg+xml").documentElement;
      const box = cardPreview.querySelector("[data-qr]");
      if (box && svg.nodeName === "svg") box.replaceChildren(document.importNode(svg, true));
      requestAnimationFrame(() => typeof fitAll === "function" && fitAll());
    } catch { /* behåll den gamla förhandsvisningen */ }
  });
  picker?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-pick-design]");
    const sel = cardEditor.querySelector('select[name="design"]');
    if (!btn || !sel) return;
    sel.value = btn.dataset.pickDesign;
    update();
  });

  // Platshållarknappar infogar i det textfält som senast hade fokus
  let lastField = cardEditor.querySelector('[data-text="body"]');
  cardEditor.addEventListener("focusin", (e) => { if (e.target.matches("[data-text]")) lastField = e.target; });
  cardEditor.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-insert]");
    if (!btn || !lastField) return;
    const t = btn.dataset.insert, s = lastField.selectionStart ?? lastField.value.length, end = lastField.selectionEnd ?? s;
    lastField.value = lastField.value.slice(0, s) + t + lastField.value.slice(end);
    lastField.focus(); lastField.setSelectionRange(s + t.length, s + t.length);
    update();
  });
}

// Trycksaker: krymp innehållet stegvis om texten inte ryms på kortet (samma proportioner på skärm och papper)
const fitCard = (card) => {
  const inner = card.querySelector(".pcard-inner");
  if (!inner || !inner.clientHeight) return 1;
  const cs = getComputedStyle(inner);
  const overflows = () => {
    const box = inner.getBoundingClientRect();
    const top = box.top + parseFloat(cs.paddingTop) + parseFloat(cs.borderTopWidth) - 1;
    const bottom = box.bottom - parseFloat(cs.paddingBottom) - parseFloat(cs.borderBottomWidth) + 1;
    const kids = [...inner.children].filter((k) => k.getClientRects().length);
    if (!kids.length) return false;
    return kids[0].getBoundingClientRect().top < top || kids[kids.length - 1].getBoundingClientRect().bottom > bottom;
  };
  let fit = 1;
  card.style.setProperty("--fit", "1");
  while (overflows() && fit > 0.45) { fit -= 0.04; card.style.setProperty("--fit", fit.toFixed(2)); }
  return fit;
};
const fitAll = () => {
  document.querySelectorAll(".pcard").forEach(fitCard);
  const note = document.querySelector("[data-fit-note]");
  const preview = document.querySelector("[data-card-preview]");
  if (note && preview) note.hidden = parseFloat(preview.style.getPropertyValue("--fit") || "1") >= 0.85;
};
if (document.querySelector(".pcard")) {
  window.addEventListener("load", fitAll);
  window.addEventListener("resize", () => { clearTimeout(window.__fitT); window.__fitT = setTimeout(fitAll, 150); });
  document.addEventListener("input", (e) => { if (e.target.closest("[data-card-editor]")) requestAnimationFrame(fitAll); });
  document.addEventListener("change", (e) => { if (e.target.closest("[data-card-editor]")) requestAnimationFrame(fitAll); });
  document.addEventListener("click", (e) => { if (e.target.closest("[data-pick-design], [data-insert]")) requestAnimationFrame(fitAll); });
}

// Dagen: timer för ett tal – räknar ner och blir röd när tiden är slut
const timerBox = document.querySelector("[data-timer]");
if (timerBox) {
  let iv = null;
  const out = timerBox.querySelector("[data-timer-left]");
  const stop = () => { clearInterval(iv); iv = null; timerBox.hidden = true; timerBox.classList.remove("over"); };
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-timer-start]");
    if (btn) {
      stop();
      const end = Date.now() + Number(btn.dataset.timerStart) * 60000;
      timerBox.querySelector("[data-timer-name]").textContent = btn.dataset.timerLabel;
      const tickT = () => {
        const left = Math.round((end - Date.now()) / 1000), a = Math.abs(left);
        out.textContent = (left < 0 ? "+" : "") + Math.floor(a / 60) + ":" + String(a % 60).padStart(2, "0");
        timerBox.classList.toggle("over", left < 0);
      };
      tickT(); iv = setInterval(tickT, 1000); timerBox.hidden = false;
    }
    if (e.target.closest("[data-timer-stop]")) stop();
  });
}
