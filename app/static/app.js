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
if (refresh) setTimeout(() => location.reload(), Number(refresh.dataset.autorefresh) * 1000);

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
