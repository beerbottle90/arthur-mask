"use strict";

const BELIRTEC = document.querySelector('meta[name="am-belirtec"]').content;
const DURUM_ADI = { hazir: "Claude'a hazır", onay_bekliyor: "Onay bekliyor", kirmizi_hat: "Kırmızı hat" };
const ETIKET = /\{\{[^{}\s]{1,40}?-\d{1,5}\}\}/g;

const durum = { aktif: null, belgeler: [], cevaplar: [], acikInceleme: null, maskeliGorunum: false };
const $ = (id) => document.getElementById(id);

async function api(yontem, yol, govde, ekBasliklar = {}) {
  const secenek = { method: yontem, headers: { "X-Arthur-Mask": BELIRTEC, ...ekBasliklar } };
  if (govde instanceof Blob || govde instanceof ArrayBuffer) {
    secenek.body = govde;
  } else if (govde !== undefined) {
    secenek.body = JSON.stringify(govde);
    secenek.headers["Content-Type"] = "application/json";
  }
  const yanit = await fetch(yol, secenek);
  const veri = await yanit.json().catch(() => ({}));
  if (!yanit.ok) throw new Error(veri.hata || `İstek başarısız (${yanit.status})`);
  return veri;
}

function el(etiket, ozellikler = {}, ...cocuklar) {
  const dugum = document.createElement(etiket);
  for (const [anahtar, deger] of Object.entries(ozellikler)) {
    if (anahtar === "sinif") dugum.className = deger;
    else if (anahtar.startsWith("on")) dugum.addEventListener(anahtar.slice(2), deger);
    else if (deger !== false && deger !== undefined) dugum.setAttribute(anahtar, deger);
  }
  for (const cocuk of cocuklar.flat()) {
    if (cocuk === null || cocuk === undefined) continue;
    dugum.append(cocuk instanceof Node ? cocuk : document.createTextNode(String(cocuk)));
  }
  return dugum;
}

/** Metni etiketleri vurgulanmış düğümlere böler (HTML yorumlanmaz). */
function etiketliMetin(metin) {
  const parca = document.createDocumentFragment();
  let imlec = 0;
  for (const eslesme of metin.matchAll(ETIKET)) {
    parca.append(document.createTextNode(metin.slice(imlec, eslesme.index)));
    parca.append(el("span", { sinif: "etiket" }, eslesme[0]));
    imlec = eslesme.index + eslesme[0].length;
  }
  parca.append(document.createTextNode(metin.slice(imlec)));
  return parca;
}

function tarih(iso) {
  return new Date(iso).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" });
}

// -- durum ---------------------------------------------------------------------------------
async function durumuYenile() {
  const kutu = $("durum");
  try {
    const d = await api("GET", "/api/durum");
    kutu.className = "durum " + (d.motor_hazir ? "hazir" : "yukleniyor");
    kutu.textContent = d.motor_hazir
      ? `Hazır · ${d.semantik ? "kurallar + semantik" : "yalnız kurallar"}`
      : "Model yükleniyor…";
  } catch {
    kutu.className = "durum hata";
    kutu.textContent = "Bağlantı yok — Claude Desktop'u açın";
  }
}

// -- dosyalar ---------------------------------------------------------------------------------
async function dosyalariYukle() {
  const { dosyalar, aktif } = await api("GET", "/api/dosyalar");
  durum.aktif = aktif;
  const liste = $("dosya-listesi");
  liste.replaceChildren(...dosyalar.map((d) => el("li", {},
    el("button", {
      sinif: "dosya" + (d.klasor === aktif ? " aktif" : ""), type: "button",
      "aria-current": d.klasor === aktif ? "true" : false,
      onclick: () => dosyaSec(d.klasor),
    }, d.ad, el("small", {}, `${d.belge_sayisi} belge · ${d.cevap_sayisi} cevap`)),
  )));
  $("secim-yok").hidden = Boolean(aktif);
  $("calisma").hidden = !aktif;
  if (aktif) await calismayiYenile();
}

async function dosyaSec(klasor) {
  await api("POST", "/api/aktif", { klasor });
  durum.acikInceleme = null;
  await dosyalariYukle();
}

$("yeni-dosya").addEventListener("submit", async (olay) => {
  olay.preventDefault();
  const girdi = $("yeni-dosya-ad");
  await api("POST", "/api/dosyalar", { ad: girdi.value });
  girdi.value = "";
  await dosyalariYukle();
});

// -- belge yükleme ---------------------------------------------------------------------------
const birak = $("birak");
birak.addEventListener("click", () => $("dosya-sec").click());
birak.addEventListener("keydown", (o) => { if (o.key === "Enter" || o.key === " ") { o.preventDefault(); $("dosya-sec").click(); } });
birak.addEventListener("dragover", (o) => { o.preventDefault(); birak.classList.add("uzerinde"); });
birak.addEventListener("dragleave", () => birak.classList.remove("uzerinde"));
birak.addEventListener("drop", (o) => { o.preventDefault(); birak.classList.remove("uzerinde"); yukle([...o.dataTransfer.files]); });
$("dosya-sec").addEventListener("change", (o) => { yukle([...o.target.files]); o.target.value = ""; });

async function yukle(dosyalar) {
  if (!durum.aktif || !dosyalar.length) return;
  birak.classList.add("isleniyor");
  const ipucu = $("birak-ipucu");
  try {
    for (const dosya of dosyalar) {
      ipucu.textContent = `${dosya.name} maskeleniyor…`;
      const sonuc = await api("POST", `/api/dosyalar/${encodeURIComponent(durum.aktif)}/belgeler`,
        await dosya.arrayBuffer(), { "X-Dosya-Adi": encodeURIComponent(dosya.name) });
      if (sonuc.durum !== "hazir") durum.acikInceleme = sonuc.id;
    }
    ipucu.textContent = ".docx · .udf · .pdf · .jpg/.png · .txt — belge bu bilgisayardan çıkmaz";
  } catch (hata) {
    ipucu.textContent = `Hata: ${hata.message}`;
  } finally {
    birak.classList.remove("isleniyor");
    await calismayiYenile();
  }
}

// -- belgeler ve inceleme ------------------------------------------------------------------------
async function calismayiYenile() {
  const k = encodeURIComponent(durum.aktif);
  const [{ belgeler }, { cevaplar }] = await Promise.all([
    api("GET", `/api/dosyalar/${k}/belgeler`),
    api("GET", `/api/dosyalar/${k}/cevaplar`),
  ]);
  // Yalnız veri değiştiğinde yeniden çiz: açık incelemedeki seçimler ve gerekçe yenilemede kaybolmasın.
  const belgeImza = JSON.stringify(belgeler.map((b) => [b.id, b.durum, b.etiket_sayisi]));
  const cevapImza = JSON.stringify(cevaplar.map((c) => [c.ad, c.cozulen]));
  const incelenen = belgeler.find((b) => b.id === durum.acikInceleme);
  const incelemeImza = incelenen ? `${incelenen.id}:${incelenen.durum}:${incelenen.etiket_sayisi}` : "";
  durum.belgeler = belgeler;
  durum.cevaplar = cevaplar;
  if (belgeImza !== durum.belgeImza) { durum.belgeImza = belgeImza; belgeleriCiz(); }
  if (cevapImza !== durum.cevapImza) { durum.cevapImza = cevapImza; cevaplariCiz(); }
  if (incelemeImza !== durum.incelemeImza) { durum.incelemeImza = incelemeImza; incelemeyiCiz(); }
}

function belgeleriCiz() {
  const hazir = durum.belgeler.find((b) => b.durum === "hazir");
  $("ornek-komut").textContent = `Arthur Mask'teki ${hazir ? hazir.id : "belge-1"}'i incele`;
  $("belge-listesi").replaceChildren(...durum.belgeler.map((b) => el("li", { sinif: "belge" },
    el("span", { sinif: "ad" }, `${b.id} · ${b.kaynak_ad} `, el("span", { sinif: `cip ${b.durum}` }, DURUM_ADI[b.durum])),
    el("span", { sinif: "meta" }, `${tarih(b.olusturma)} · ${b.etiket_sayisi} etiket · ${Object.entries(b.turler).map(([t, n]) => `${t} ${n}`).join(", ") || "etiket yok"}`),
    el("span", { sinif: "eylemler" },
      el("button", { type: "button", sinif: b.durum === "hazir" ? "ikincil" : "", onclick: () => { durum.acikInceleme = b.id; durum.incelemeImza = `${b.id}:${b.durum}:${b.etiket_sayisi}`; incelemeyiCiz(); } },
        b.durum === "hazir" ? "Önizle" : "İncele"),
      el("button", { type: "button", sinif: "ikincil", "aria-label": `${b.id} sil`, onclick: () => belgeSil(b.id) }, "Sil")),
  )));
}

async function belgeSil(id) {
  await api("DELETE", `/api/dosyalar/${encodeURIComponent(durum.aktif)}/belgeler/${id}`);
  if (durum.acikInceleme === id) durum.acikInceleme = null;
  await calismayiYenile();
}

function incelemeyiCiz() {
  const panel = $("inceleme");
  const belge = durum.belgeler.find((b) => b.id === durum.acikInceleme);
  panel.hidden = !belge;
  if (!belge) return;
  const icerik = $("inceleme-icerik");
  const bolumler = [el("p", {}, `${belge.id} · ${belge.kaynak_ad} · `, el("span", { sinif: `cip ${belge.durum}` }, DURUM_ADI[belge.durum]))];

  for (const uyari of belge.uyarilar) bolumler.push(el("p", { sinif: "uyari" }, `⚠ ${uyari}`));
  if (belge.yeniden_yukleme_gerekli) {
    bolumler.push(el("p", { sinif: "hata-mesaji" }, "Bu belgenin inceleme bilgisi bu oturumda yok. Belgeyi silip yeniden yükleyin."));
  }

  let gerekce = null;
  if (belge.durum !== "hazir" && belge.kirmizi_hat.length) {
    gerekce = el("textarea", { rows: "2", placeholder: "Gönderim gerekçesi (kayda geçer)", "aria-label": "Kırmızı hat gerekçesi" });
    bolumler.push(el("div", { sinif: "kirmizi-kutu" },
      el("strong", {}, "Kırmızı hat — maskelense de içerik gizlenmez"),
      el("ul", {}, belge.kirmizi_hat.map((k) => el("li", {}, `${k.kategori} (satır ${k.satirlar.slice(0, 8).join(", ")})`))),
      gerekce));
  }

  const secimler = [];
  if (belge.durum !== "hazir" && belge.supheli.length) {
    bolumler.push(el("h3", {}, `Şüpheli adaylar (${belge.supheli.length})`));
    for (const aday of belge.supheli) {
      const ad = `aday-${belge.id}-${aday.sira}`;
      const maskele = el("input", { type: "radio", name: ad, value: "maskele", checked: "checked" });
      const birakRadyo = el("input", { type: "radio", name: ad, value: "birak" });
      secimler.push({ sira: aday.sira, maskele });
      const i = aday.baglam.indexOf(aday.metin);
      const baglam = i < 0 ? [aday.baglam] : [aday.baglam.slice(0, i), el("mark", {}, aday.metin), aday.baglam.slice(i + aday.metin.length)];
      bolumler.push(el("div", { sinif: "aday" },
        el("div", { sinif: "secim" }, el("label", {}, maskele, "Maskele"), el("label", {}, birakRadyo, "Bırak")),
        el("div", {}, el("strong", {}, aday.metin), ` · ${aday.tur} · ${aday.skor.toFixed(2)}`),
        el("div", { sinif: "baglam" }, "…", baglam, "…")));
    }
  }
  if (belge.artik.length) {
    bolumler.push(el("p", { sinif: "uyari" }, `Artık tarama: ${belge.artik.map((a) => `satır ${a.satir} ${a.aciklama}`).join("; ")}`));
  }

  bolumler.push(el("div", { sinif: "eylem-satiri" },
    el("button", { type: "button", sinif: belge.ocr ? "" : "ikincil", onclick: () => maskeliKopyaAc(belge) },
      belge.ocr ? "Maskeli sayfa görüntülerini kontrol et (PDF)" : "Maskeli kopyayı aç")));
  bolumler.push(el("h3", {}, "Claude'a gidecek metin"));
  bolumler.push(el("div", { sinif: "onizleme", tabindex: "0" }, etiketliMetin(belge.maskeli_metin)));

  const hata = el("p", { sinif: "hata-mesaji", role: "alert" });
  const eylemler = el("div", { sinif: "eylem-satiri" });
  if (belge.durum !== "hazir") {
    eylemler.append(el("button", {
      type: "button",
      onclick: async (o) => {
        o.target.disabled = true;
        try {
          await api("POST", `/api/dosyalar/${encodeURIComponent(durum.aktif)}/belgeler/${belge.id}/onay`, {
            maskelenecek: secimler.filter((s) => s.maskele.checked).map((s) => s.sira),
            birakilacak: secimler.filter((s) => !s.maskele.checked).map((s) => s.sira),
            gerekce: gerekce ? gerekce.value : "",
          });
          await calismayiYenile();
        } catch (h) {
          hata.textContent = h.message;
          o.target.disabled = false;
        }
      },
    }, "Onayla ve Claude'a hazırla"));
  }
  eylemler.append(el("button", { type: "button", sinif: "ikincil", onclick: () => { durum.acikInceleme = null; durum.incelemeImza = ""; incelemeyiCiz(); } }, "Kapat"));
  bolumler.push(hata, eylemler);
  icerik.replaceChildren(...bolumler);
}

// -- cevaplar --------------------------------------------------------------------------------------
$("maskeli-gorunum").addEventListener("change", (o) => { durum.maskeliGorunum = o.target.checked; cevaplariCiz(); });

function cevaplariCiz() {
  const liste = $("cevap-listesi");
  if (!durum.cevaplar.length) {
    liste.replaceChildren(el("li", { sinif: "not" }, "Claude bir taslak teslim ettiğinde burada çözülmüş hâliyle görünür."));
    return;
  }
  liste.replaceChildren(...durum.cevaplar.map((c) => el("li", { sinif: "cevap" },
    el("span", { sinif: "ad" }, c.baslik),
    el("span", { sinif: "meta" }, `${tarih(c.olusturma)} · ${c.bicim.toUpperCase()} · ${c.cozulen} etiket çözüldü`,
      c.bilinmeyen.length ? ` · ⚠ kasada olmayan: ${c.bilinmeyen.join(", ")}` : ""),
    el("span", { sinif: "eylemler" }, el("button", { type: "button", onclick: () => indir(c) }, "İndir")),
    el("div", { sinif: "metin onizleme", tabindex: "0" },
      durum.maskeliGorunum ? etiketliMetin(c.maskeli_metin) : c.acik_metin),
  )));
}

async function maskeliKopyaAc(belge) {
  const yanit = await fetch(`/api/dosyalar/${encodeURIComponent(durum.aktif)}/maskeli-dosyasi?id=${encodeURIComponent(belge.id)}`,
    { headers: { "X-Arthur-Mask": BELIRTEC } });
  if (!yanit.ok) return;
  const adres = URL.createObjectURL(await yanit.blob());
  window.open(adres, "_blank", "noopener");
  setTimeout(() => URL.revokeObjectURL(adres), 60000);
}

async function indir(cevap) {
  const yanit = await fetch(`/api/dosyalar/${encodeURIComponent(durum.aktif)}/cevap-dosyasi?ad=${encodeURIComponent(cevap.dosya)}`,
    { headers: { "X-Arthur-Mask": BELIRTEC } });
  if (!yanit.ok) return;
  const baglanti = el("a", { href: URL.createObjectURL(await yanit.blob()), download: cevap.dosya });
  document.body.append(baglanti);
  baglanti.click();
  setTimeout(() => { URL.revokeObjectURL(baglanti.href); baglanti.remove(); }, 1000);
}

// -- başlangıç ---------------------------------------------------------------------------------------
durumuYenile();
dosyalariYukle().catch(() => {});
setInterval(durumuYenile, 5000);
setInterval(() => { if (durum.aktif) calismayiYenile().catch(() => {}); }, 4000);
