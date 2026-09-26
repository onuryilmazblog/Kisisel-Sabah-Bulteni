/* Kişisel Sabah Bülteni — küçük istemci betiği (derleme adımı yok). */
(function () {
  "use strict";
  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  function toast(msg) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.remove("show"), 3500);
  }

  async function post(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "X-CSRF-Token": csrf, "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : "{}",
      credentials: "same-origin",
    });
    let data = {};
    try { data = await res.json(); } catch (e) { /* boş yanıt */ }
    if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
    return data;
  }

  // Kart aksiyonları: Okudum / Takip et / Sustur
  document.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-act]");
    if (!btn) return;
    const card = btn.closest("[data-event]");
    if (!card) return;
    btn.disabled = true;
    try {
      const r = await post(`/api/olay/${card.dataset.event}/${btn.dataset.act}?v=${card.dataset.version}`);
      toast(r.message || "Tamam");
      const flip = { read: ["unread", "Okunmadı"], unread: ["read", "Okudum"], follow: ["unfollow", "Takipten çık"],
        unfollow: ["follow", "Takip et"], mute: ["unmute", "Susturmayı kaldır"], unmute: ["mute", "Sustur"] };
      const next = flip[btn.dataset.act];
      if (next) { btn.dataset.act = next[0]; btn.textContent = next[1]; }
      if (btn.dataset.act === "unread") card.classList.add("is-read");
      if (btn.dataset.act === "read") card.classList.remove("is-read");
    } catch (e) { toast("Hata: " + e.message); }
    btn.disabled = false;
  });

  // İşler: Şimdi kontrol et, bülteni gönder, test mesajları
  document.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-job]");
    if (!btn) return;
    btn.disabled = true;
    try {
      const r = await post(`/api/is/${btn.dataset.job}`);
      toast(r.message);
      if (r.worker_alive) poll(r.request_id, btn);
      else btn.disabled = false;
    } catch (e) { toast("Hata: " + e.message); btn.disabled = false; }
  });

  async function poll(id, btn, tries) {
    tries = tries || 0;
    if (tries > 90) { btn.disabled = false; toast("İş hâlâ sürüyor; Sistem durumu sayfasından izleyin."); return; }
    try {
      const res = await fetch(`/api/is/${id}`, { credentials: "same-origin" });
      const r = await res.json();
      if (r.status === "done" || r.status === "error") {
        btn.disabled = false;
        toast((r.status === "done" ? "Tamamlandı: " : "Hata: ") + (r.detail || ""));
        if (r.status === "done" && btn.dataset.job === "check_now") setTimeout(() => location.reload(), 1500);
        return;
      }
    } catch (e) { /* yeniden dene */ }
    setTimeout(() => poll(id, btn, tries + 1), 2000);
  }

  // Demo verisi
  document.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-demo]");
    if (!btn) return;
    ev.preventDefault();
    btn.disabled = true;
    try { await post(`/api/demo/${btn.dataset.demo}`); location.href = "/"; }
    catch (e) { toast("Hata: " + e.message); btn.disabled = false; }
  });

  // Kaynak test / aç-kapat
  document.addEventListener("click", async (ev) => {
    const t = ev.target.closest("[data-test-source]");
    const g = ev.target.closest("[data-toggle-source]");
    const r = ev.target.closest("[data-resend]");
    if (t) {
      const row = t.closest("tr");
      const out = row.querySelector(".test-result");
      t.disabled = true; out.textContent = "Test ediliyor…";
      try {
        const d = await post(`/api/kaynak/${t.dataset.testSource}/test`);
        out.textContent = d.error ? ((d.not_configured ? "Yapılandırılmadı: " : "Hata: ") + d.error)
          : `${d.ok ? "Yapı tanındı" : "Yapı TANINMADI"} · ${d.items} kayıt · ${d.duration_ms} ms` +
            (d.warnings && d.warnings.length ? " · Uyarı: " + d.warnings.join("; ") : "") +
            (d.sample && d.sample.length ? " · Örnek: " + d.sample[0] : "");
      } catch (e) { out.textContent = "Hata: " + e.message; }
      t.disabled = false;
    } else if (g) {
      try { await post(`/api/kaynak/${g.dataset.toggleSource}/durum?acik=${g.dataset.on}`); location.reload(); }
      catch (e) { toast("Hata: " + e.message); }
    } else if (r) {
      if (!confirm("Belirsiz/başarısız parçalar yeniden gönderilecek. Önceki gönderim ulaşmışsa kopya oluşabilir. Devam?")) return;
      try { await post(`/api/teslimat/${r.dataset.resend}/yeniden`); toast("Yeniden gönderim sıraya alındı."); }
      catch (e) { toast("Hata: " + e.message); }
    }
  });

  // Geri bağlantısı
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-back]");
    if (b && history.length > 1) { ev.preventDefault(); history.back(); }
  });

  // Konum arama (Ayarlar)
  const locBtn = document.getElementById("loc-search");
  if (locBtn) {
    const q = document.getElementById("loc-q");
    const list = document.getElementById("loc-results");
    const hidden = document.getElementById("location_json");
    const current = document.getElementById("loc-current");
    async function search() {
      list.innerHTML = "<li>Aranıyor…</li>";
      try {
        const res = await fetch(`/api/konum?q=${encodeURIComponent(q.value)}`, { credentials: "same-origin" });
        const d = await res.json();
        list.innerHTML = "";
        if (d.error) { list.innerHTML = `<li></li>`; list.firstChild.textContent = d.error; return; }
        if (!d.results.length) { list.innerHTML = "<li>Sonuç yok.</li>"; return; }
        d.results.forEach((r) => {
          const li = document.createElement("li");
          const b = document.createElement("button");
          b.type = "button"; b.className = "btn small";
          b.textContent = [r.name, r.admin2, r.admin1, r.country].filter(Boolean).join(", ");
          b.addEventListener("click", () => {
            hidden.value = JSON.stringify(r);
            current.textContent = b.textContent + " (kaydetmeyi unutmayın)";
            list.innerHTML = "";
          });
          li.appendChild(b); list.appendChild(li);
        });
      } catch (e) { list.innerHTML = "<li>Arama başarısız.</li>"; }
    }
    locBtn.addEventListener("click", search);
    q.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); search(); } });
  }

  // "Uygulamada görüntülendi": ekranda en az 1 sn görünen kartlar (okundu SAYILMAZ)
  if ("IntersectionObserver" in window) {
    const seen = new Set();
    let queue = [];
    const flush = () => {
      if (!queue.length) return;
      const ids = queue; queue = [];
      post("/api/gorunum", { ids }).catch(() => {});
    };
    const timers = new Map();
    const io = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        const id = en.target.dataset.event;
        if (en.isIntersecting && !seen.has(id)) {
          timers.set(id, setTimeout(() => { seen.add(id); queue.push(Number(id)); }, 1000));
        } else if (!en.isIntersecting && timers.has(id)) {
          clearTimeout(timers.get(id)); timers.delete(id);
        }
      });
    }, { threshold: 0.5 });
    document.querySelectorAll("[data-event]").forEach((el) => io.observe(el));
    setInterval(flush, 4000);
    window.addEventListener("pagehide", flush);
  }
})();
