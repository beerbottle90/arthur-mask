"use strict";

const BELIRTEC = document.querySelector('meta[name="am-belirtec"]').content;
const DURUM_ADI = { hazir: "Claude'a hazır", onay_bekliyor: "Onayınızı bekliyor", kirmizi_hat: "Kırmızı hat" };
const BICIM_ADI = { docx: "Word'de aç", udf: "UYAP editöründe aç", txt: "Aç" };
const ETIKET = /\{\{[^{}\s]{1,40}?-\d{1,5}\}\}/g;
const IPUCU = "Word · UDF · PDF · taranmış görüntü · metin — belge bu bilgisayardan çıkmaz";

const durum = { aktif: null, belgeler: [], cevaplar: [], acikInceleme: null, kaydir: false, maskeliGorunum: false };
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
    if (cocuk === null || cocuk === undefined || cocuk === false) continue;
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

const tarih = (iso) => new Date(iso).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" });

async function kopyala(metin, dugme) {
  try {
    await navigator.clipboard.writeText(metin);
    const eski = dugme.textContent;
    dugme.textContent = "Kopyalandı ✓";
    setTimeout(() => { dugme.textContent = eski; }, 1500);
  } catch { /* pano izni yoksa sessiz geç */ }
}

// -- durum ve kurtarma anahtarı ----------------------------------------------------------------
async function durumuYenile() {
  const kopru = $("kopru-durumu");
  const koruma = $("koruma-durumu");
  try {
    const d = await api("GET", "/api/durum");
    kopru.className = "durum " + (d.kopru ? "hazir" : "yukleniyor");
    kopru.textContent = d.kopru ? "Claude Desktop'a bağlı" : "Yalnız arayüz (Claude bağlı değil)";
    koruma.hidden = false;
    if (!d.motor_hazir) {
      koruma.className = "durum yukleniyor";
      koruma.textContent = "Koruma hazırlanıyor…";
    } else {
      const tam = d.semantik && d.ocr;
      koruma.className = "durum " + (tam ? "hazir" : "yukleniyor");
      koruma.textContent = tam ? "Tam koruma" : "Temel koruma";
      koruma.title = `Kurallar${d.semantik ? " + yapay zekâ ad tespiti" : ""}${d.ocr ? " + taranmış belge okuma" : ""}`;
    }
    $("kurtarma").hidden = d.kurtarma_saklandi;
  } catch {
    kopru.className = "durum hata";
    kopru.textContent = "Bağlantı yok — Claude Desktop'u açın";
    koruma.hidden = true;
  }
}

$("kurtarma-goster").addEventListener("click", async () => {
  const { kod } = await api("GET", "/api/kurtarma");
  const kutu = $("kurtarma-kod");
  kutu.textContent = kod;
  kutu.hidden = false;
  $("kurtarma-goster").hidden = true;
  $("kurtarma-kopyala").hidden = false;
  $("kurtarma-onay").hidden = false;
});
$("kurtarma-kopyala").addEventListener("click", (o) => kopyala($("kurtarma-kod").textContent, o.target));
$("kurtarma-onay").addEventListener("click", async () => {
  await api("POST", "/api/kurtarma/onay");
  $("kurtarma-kod").textContent = "";
  $("kurtarma").hidden = true;
});

// -- dosyalar ---------------------------------------------------------------------------------
async function dosyalariYukle() {
  const { dosyalar, aktif } = await api("GET", "/api/dosyalar");
  durum.aktif = aktif;
  $("dosya-listesi").replaceChildren(...dosyalar.map((d) => el("li", {},
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
  durum.belgeImza = durum.cevapImza = durum.incelemeImza = undefined;
  await dosyalariYukle();
}

$("yeni-dosya").addEventListener("submit", async (olay) => {
  olay.preventDefault();
  const girdi = $("yeni-dosya-ad");
  await api("POST", "/api/dosyalar", { ad: girdi.value });
  girdi.value = "";
  durum.belgeImza = durum.cevapImza = durum.incelemeImza = undefined;
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
      if (sonuc.durum !== "hazir") { durum.acikInceleme = sonuc.id; durum.kaydir = true; }
    }
    ipucu.textContent = IPUCU;
  } catch (hata) {
    ipucu.textContent = `Olmadı: ${hata.message}`;
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

const TUR_OKUNUR = {
  "KİŞİ": "kişi", "ŞİRKET": "şirket", "ADRES": "adres", "TELEFON": "telefon", "EPOSTA": "e-posta",
  "DOSYA_NO": "dosya no", "DOĞUM_TARİHİ": "doğum tarihi", "PASAPORT": "pasaport", "PLAKA": "plaka",
  "NUMARA": "numara", "GİZLİ": "gizli ifade",
};
function turOzeti(turler) {
  return Object.entries(turler).map(([t, n]) => `${n} ${TUR_OKUNUR[t] || t}`).join(", ");
}

function belgeleriCiz() {
  const hazir = durum.belgeler.find((b) => b.durum === "hazir");
  $("komut-kutusu").hidden = !hazir;
  if (hazir) $("ornek-komut").textContent = `Arthur Mask'teki ${hazir.id}'i incele`;
  if (!durum.belgeler.length) {
    $("belge-listesi").replaceChildren(el("li", { sinif: "not" }, "Henüz belge yok. Yukarıdaki alana bir belge bırakın."));
    return;
  }
  $("belge-listesi").replaceChildren(...durum.belgeler.map((b) => el("li", { sinif: "belge" },
    el("span", { sinif: "ad" }, `${b.kaynak_ad} `, el("span", { sinif: `cip ${b.durum}` }, DURUM_ADI[b.durum])),
    el("span", { sinif: "meta" }, `${b.id} · ${tarih(b.olusturma)} · ${b.etiket_sayisi} etiket${b.etiket_sayisi ? ": " + turOzeti(b.turler) : ""}`),
    el("span", { sinif: "eylemler" },
      el("button", { type: "button", sinif: b.durum === "hazir" ? "ikincil" : "", onclick: () => incelemeAc(b) },
        b.durum === "hazir" ? "Önizle" : "İncele"),
      el("button", { type: "button", sinif: "ikincil", "aria-label": `${b.kaynak_ad} sil`, onclick: () => belgeSil(b.id) }, "Sil")),
  )));
}

function incelemeAc(belge) {
  durum.acikInceleme = belge.id;
  durum.incelemeImza = `${belge.id}:${belge.durum}:${belge.etiket_sayisi}`;
  durum.kaydir = true;
  incelemeyiCiz();
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
  const bekliyor = belge.durum !== "hazir";
  const bolumler = [el("p", {}, el("strong", {}, belge.kaynak_ad), " · ", el("span", { sinif: `cip ${belge.durum}` }, DURUM_ADI[belge.durum]))];

  for (const uyari of belge.uyarilar) bolumler.push(el("p", { sinif: "uyari" }, `⚠ ${uyari}`));
  if (belge.yeniden_yukleme_gerekli) {
    bolumler.push(el("p", { sinif: "hata-mesaji" }, "Bu belgenin inceleme bilgisi bu oturumda yok. Belgeyi silip yeniden bırakın."));
  }

  let gerekce = null;
  if (bekliyor && belge.kirmizi_hat.length) {
    gerekce = el("textarea", { rows: "2", placeholder: "Neden yine de gönderiyorsunuz? (kayda geçer)", "aria-label": "Kırmızı hat gerekçesi" });
    bolumler.push(el("div", { sinif: "kirmizi-kutu" },
      el("strong", {}, "Kırmızı hat — maskelense de içerik gizlenmez"),
      el("ul", {}, belge.kirmizi_hat.map((k) => el("li", {}, `${k.kategori} (satır ${k.satirlar.slice(0, 8).join(", ")})`))),
      gerekce));
  }

  const secimler = [];
  if (bekliyor && belge.supheli.length) {
    bolumler.push(el("h3", {}, `Emin olunamayanlar (${belge.supheli.length}) — maskelensin mi?`));
    for (const aday of belge.supheli) {
      const ad = `aday-${belge.id}-${aday.sira}`;
      const maskele = el("input", { type: "radio", name: ad, value: "maskele", checked: "checked" });
      const birakRadyo = el("input", { type: "radio", name: ad, value: "birak" });
      secimler.push({ sira: aday.sira, maskele });
      const i = aday.baglam.indexOf(aday.metin);
      const baglam = i < 0 ? [aday.baglam] : [aday.baglam.slice(0, i), el("mark", {}, aday.metin), aday.baglam.slice(i + aday.metin.length)];
      bolumler.push(el("div", { sinif: "aday" },
        el("div", { sinif: "secim" }, el("label", {}, maskele, "Maskele"), el("label", {}, birakRadyo, "Açık bırak")),
        el("div", {}, el("strong", {}, aday.metin), " ", el("span", { sinif: "tur" }, aday.tur)),
        el("div", { sinif: "baglam" }, "…", baglam, "…")));
    }
  }

  bolumler.push(el("div", { sinif: "eylem-satiri sol" },
    el("button", { type: "button", sinif: belge.ocr ? "" : "ikincil", onclick: () => maskeliKopyaAc(belge) },
      belge.ocr ? "Maskeli sayfaları kontrol et (PDF)" : "Maskeli kopyayı aç")));
  bolumler.push(el("h3", {}, "Claude'un göreceği metin"));
  bolumler.push(el("div", { sinif: "onizleme", tabindex: "0" }, etiketliMetin(belge.maskeli_metin)));

  const hata = el("p", { sinif: "hata-mesaji", role: "alert" });
  const eylemler = el("div", { sinif: "eylem-satiri" });
  if (bekliyor) {
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
    }, "Onayla — Claude'a hazırla"));
  }
  eylemler.append(el("button", { type: "button", sinif: "ikincil", onclick: () => { durum.acikInceleme = null; durum.incelemeImza = ""; incelemeyiCiz(); } }, "Kapat"));
  bolumler.push(hata, eylemler);
  $("inceleme-icerik").replaceChildren(...bolumler);
  if (durum.kaydir) {
    durum.kaydir = false;
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

async function maskeliKopyaAc(belge) {
  const yanit = await fetch(`/api/dosyalar/${encodeURIComponent(durum.aktif)}/maskeli-dosyasi?id=${encodeURIComponent(belge.id)}`,
    { headers: { "X-Arthur-Mask": BELIRTEC } });
  if (!yanit.ok) return;
  const adres = URL.createObjectURL(await yanit.blob());
  window.open(adres, "_blank", "noopener");
  setTimeout(() => URL.revokeObjectURL(adres), 60000);
}

$("komut-kopyala").addEventListener("click", (o) => kopyala($("ornek-komut").textContent, o.target));

// -- cevaplar --------------------------------------------------------------------------------------
$("maskeli-gorunum").addEventListener("change", (o) => { durum.maskeliGorunum = o.target.checked; cevaplariCiz(); });

function cevaplariCiz() {
  const liste = $("cevap-listesi");
  if (!durum.cevaplar.length) {
    liste.replaceChildren(el("li", { sinif: "not" }, "Claude bir taslak teslim ettiğinde burada gerçek adlarla görünür ve tek tıkla açılır."));
    return;
  }
  liste.replaceChildren(...durum.cevaplar.map((c) => el("li", { sinif: "cevap" },
    el("span", { sinif: "ad" }, c.baslik),
    el("span", { sinif: "meta" }, `${tarih(c.olusturma)} · ${c.bicim.toUpperCase()} · ${c.cozulen} etiket çözüldü`,
      c.bilinmeyen.length ? ` · ⚠ tanınmayan etiket: ${c.bilinmeyen.join(", ")}` : ""),
    el("span", { sinif: "eylemler" },
      el("button", { type: "button", onclick: () => cevapAc(c, false) }, BICIM_ADI[c.bicim] || "Aç"),
      el("button", { type: "button", sinif: "ikincil", onclick: () => cevapAc(c, true) }, "Klasörde göster")),
    el("div", { sinif: "metin onizleme", tabindex: "0" },
      durum.maskeliGorunum ? etiketliMetin(c.maskeli_metin) : c.acik_metin),
  )));
}

async function cevapAc(cevap, klasorde) {
  await api("POST", `/api/dosyalar/${encodeURIComponent(durum.aktif)}/cevap-ac`, { dosya: cevap.dosya, klasorde });
}

// -- başlangıç ---------------------------------------------------------------------------------------
// Doğrudan bağlantı: #belge=belge-2 incelemeyi açar.
const hashBelge = new URLSearchParams(location.hash.slice(1)).get("belge");
if (hashBelge) durum.acikInceleme = hashBelge;

durumuYenile();
dosyalariYukle().catch(() => {});
setInterval(durumuYenile, 5000);
setInterval(() => { if (durum.aktif) calismayiYenile().catch(() => {}); }, 4000);
