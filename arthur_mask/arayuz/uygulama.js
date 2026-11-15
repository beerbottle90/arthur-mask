"use strict";

// Belirteç sayfada değil: masaüstü kısayolu sayfayı "#t=<belirteç>" ile açar, bu tarayıcı onu hatırlar. Aynı
// bilgisayardaki başka bir hesabın tarayıcısında belirteç olmadığı için API ona kapalı kalır.
const BELIRTEC = belirteciAl();
// Sayfa zaten açıkken kısayol aynı sekmeye "#t=" getirirse tarayıcı yeniden yüklemez; belirteci alıp baştan başla.
window.addEventListener("hashchange", () => {
  if (new URLSearchParams(location.hash.slice(1)).has("t")) { belirteciAl(); location.reload(); }
});

function belirteciAl() {
  const parametreler = new URLSearchParams(location.hash.slice(1));
  const gelen = parametreler.get("t");
  let kayitli = "";
  try {
    if (gelen) localStorage.setItem("am-belirtec", gelen);
    kayitli = localStorage.getItem("am-belirtec") || "";
  } catch { /* depolama kapalı: belirteç yalnız bu sekmede */ }
  if (gelen) {
    parametreler.delete("t");
    const kalan = parametreler.toString();
    history.replaceState(null, "", location.pathname + location.search + (kalan ? `#${kalan}` : ""));
  }
  return gelen || kayitli;
}

// -- dil -----------------------------------------------------------------------------------------------
// Türkçe, Azerbaycanca, İngilizce. Kaynak metin Türkçedir ve sözlüğün anahtarıdır (dil-az.json, dil-en.json).
//   cev(metin, değer…)  o anki dile çevirir, {0}, {1} yerlerine değerleri koyar (işlev içinde)
//   cevN(metin)         yalnız işaretler (tablo ve sabitlerde); ekrana yazılırken cev() ile çevrilir
//   cevS(metin)         sunucunun Türkçe ürettiği metin (hata, uyarı, tutarlılık bulgusu): sözlükte birebir ya da
//                       {0}/{ad} kalıbıyla eşlenir; eşleşmezse Türkçe kalır
// Sabit HTML metni data-cev ile, öznitelikler data-cev-a="aria-label title" ile işaretlidir. Karşılığı olmayan metin
// Türkçe kalır: eksik çeviri ekranı bozmaz (testler eksiği yakalar). Claude'un cevabı, belge metni, marka adları ve
// {{KİŞİ-01}} gibi etiketler çevrilmez.
const DIL = (() => {
  const DILLER = ["tr", "az", "en"];
  const YEREL = { tr: "tr-TR", az: "az-Latn-AZ", en: "en-GB" };
  const sozluk = { tr: {} };
  let secili = "tr";
  let kaliplar = null;

  async function yukle(d) {
    if (sozluk[d]) return;
    try {
      const yanit = await fetch(`dil-${d}.json`, { cache: "no-cache" });
      sozluk[d] = yanit.ok ? await yanit.json() : {};
    } catch { sozluk[d] = {}; }
  }
  const karsilik = (anahtar) => (secili === "tr" ? undefined : (sozluk[secili] || {})[anahtar]);
  const kacir = (m) => m.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  function kaliplariKur() {
    kaliplar = Object.keys(sozluk[secili] || {}).filter((k) => /\{\w+\}/.test(k)).map((k) => {
      const adlar = [];
      let desen = "^";
      let imlec = 0;
      for (const m of k.matchAll(/\{(\w+)\}/g)) {
        desen += kacir(k.slice(imlec, m.index)) + "([\\s\\S]*?)";
        adlar.push(m[1]);
        imlec = m.index + m[0].length;
      }
      return { anahtar: k, adlar, re: new RegExp(desen + kacir(k.slice(imlec)) + "$"), sabit: k.replace(/\{\w+\}/g, "").length };
    }).filter((k) => k.sabit >= 4).sort((a, b) => b.sabit - a.sabit);
  }

  function sunucu(metin) {
    if (typeof metin !== "string" || !metin || secili === "tr") return metin;
    const birebir = karsilik(metin);
    if (birebir != null) return birebir;
    if (!kaliplar) kaliplariKur();
    for (const k of kaliplar) {
      const m = k.re.exec(metin);
      if (!m) continue;
      const deger = {};
      k.adlar.forEach((ad, i) => { deger[ad] = m[i + 1]; });
      return karsilik(k.anahtar).replace(/\{(\w+)\}/g, (t, ad) => (ad in deger ? veri(deger[ad]) : t));
    }
    return metin;
  }

  // Kalıptaki değer çoğu kez belge verisidir ve çevrilmez; yalnız sunucunun kendi sözcükleri ("tutar") ve sayım
  // özetleri ("3 paragraf değişti, 1 tablo eklendi") çevrilir.
  function veri(x) {
    if (VERI_SOZCUKLERI.has(x)) return karsilik(x) ?? x;
    const parcalar = x.split(", ");
    if (parcalar.every((p) => /^\d+ \D/.test(p) || p === SAYIM_YOK)) return parcalar.map(sunucu).join(", ");
    return x;
  }

  function sabitler() {
    document.querySelectorAll("[data-cev]").forEach((e) => {
      if (!e.dataset.cev) e.dataset.cev = e.textContent.trim();
      const k = karsilik(e.dataset.cev);
      e.textContent = k == null ? e.dataset.cev : k;
    });
    document.querySelectorAll("[data-cev-a]").forEach((e) => {
      for (const ad of e.dataset.cevA.split(/\s+/).filter(Boolean)) {
        const sakla = "cevOz" + ad.replace(/-/g, "");
        if (!(sakla in e.dataset)) e.dataset[sakla] = e.getAttribute(ad) || "";
        const k = karsilik(e.dataset[sakla]);
        e.setAttribute(ad, k == null ? e.dataset[sakla] : k);
      }
    });
  }

  async function sec(d) {
    if (!DILLER.includes(d)) return false;
    await yukle(d);
    const degisti = d !== secili;
    secili = d;
    kaliplar = null;
    document.documentElement.lang = d;
    document.querySelectorAll(".dil-secimi [data-dil]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.dil === d)));
    sabitler();
    return degisti;
  }

  return { DILLER, sec, sabitler, sunucu, veri, karsilik, yerel: () => YEREL[secili], get secili() { return secili; } };
})();

function cev(anahtar, ...deger) {
  const kalip = DIL.karsilik(anahtar) ?? anahtar;
  return deger.length ? kalip.replace(/\{(\d+)\}/g, (m, i) => (+i < deger.length ? String(deger[+i]) : m)) : kalip;
}
const cevN = (anahtar) => anahtar;
const cevS = (metin) => DIL.sunucu(metin);
const VERI_SOZCUKLERI = new Set([cevN("tutar"), cevN("oran"), cevN("tarih"), cevN("sayı"), cevN("atıf"), cevN("uzantısız")]);
const SAYIM_YOK = cevN("gövde metninde fark bulunmadı");

// -- yardımcılar -------------------------------------------------------------------------------------------
function kisayoldanAcUyarisi() {
  if (document.getElementById("kisayol-uyarisi")) return;
  try { localStorage.removeItem("am-belirtec"); } catch { /* depolama kapalı */ }
  document.body.prepend(el("div", { sinif: "denetim bulgu", id: "kisayol-uyarisi", role: "alert" },
    el("strong", {}, cev("ArthurMask'i kısayolundan açın")),
    el("p", {}, cev("Güvenlik için arayüz bu bilgisayardaki ArthurMask kısayoluyla (masaüstü ya da Başlat menüsü; Mac'te Uygulamalar) bir kez açılmalı. Sonra bu tarayıcı sizi tanır; Claude'un verdiği bağlantılar da çalışır."))));
}

// Görünüm, AL Masası'ndaki gibi: açık (varsayılan), koyu ya da otomatik (sistemin temasına uyar). Bu tarayıcıda saklanır.
const tema = {
  anahtar: "al.tema",
  gecici: null,
  secim() {
    try { return this.gecici || localStorage.getItem(this.anahtar) || "acik"; } catch { return this.gecici || "acik"; }
  },
  sec(deger) {
    this.gecici = deger;
    try { localStorage.setItem(this.anahtar, deger); } catch { /* depolama kapalı: yalnız bu sekme */ }
    this.uygula();
  },
  uygula() {
    const s = this.secim();
    const koyu = s === "koyu" || (s === "otomatik" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.dataset.tema = koyu ? "koyu" : "acik";
    document.querySelectorAll(".tema-secimi [data-tema]").forEach((d) => d.setAttribute("aria-pressed", String(d.dataset.tema === s)));
  },
};
document.querySelectorAll(".tema-secimi [data-tema]").forEach((d) => d.addEventListener("click", () => tema.sec(d.dataset.tema)));
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => tema.uygula());
tema.uygula();

const DURUM_ADI = { hazir: cevN("Claude'a hazır"), onay_bekliyor: cevN("Onayınızı bekliyor"), kirmizi_hat: cevN("Kırmızı hat") };
const BICIM_ADI = { docx: cevN("Word'de aç"), udf: cevN("UYAP editöründe aç"), txt: cevN("Aç") };
const ETIKET = /\{\{[^{}\s]{1,40}?-\d{1,5}\}\}/g;
const ipucu = () => cev("Word · UDF · PDF · taranmış görüntü · metin — belge bu bilgisayardan çıkmaz");

const durum = { aktif: null, yeniDosya: false, belgeler: [], cevaplar: [], gidenler: null, acikInceleme: null, kaydir: false, cevapGorunum: {} };
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
  if (yanit.status === 401) kisayoldanAcUyarisi();
  const veri = await yanit.json().catch(() => ({}));
  if (!yanit.ok) {
    const hata = new Error(veri.hata ? cevS(veri.hata) : cev("İstek başarısız ({0})", yanit.status));
    hata.durum = yanit.status;
    throw hata;
  }
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

const tarih = (iso) => new Date(iso).toLocaleString(DIL.yerel(), { dateStyle: "short", timeStyle: "short" });
const saat = (sn) => new Date(sn * 1000).toLocaleTimeString(DIL.yerel(), { hour: "2-digit", minute: "2-digit" });

async function kopyala(metin, dugme) {
  try {
    await navigator.clipboard.writeText(metin);
    const eski = dugme.textContent;
    dugme.textContent = cev("Kopyalandı ✓");
    setTimeout(() => { dugme.textContent = eski; }, 1500);
  } catch { /* pano izni yoksa sessiz geç */ }
}

// Dış bağlantılar yalnız ArthurLegal'in GitHub sayfalarına açılır.
const BAGLANTI_ONEKI = "https://github.com/beerbottle90/";
function disAc(adres) {
  if (typeof adres === "string" && adres.startsWith(BAGLANTI_ONEKI)) window.open(adres, "_blank", "noopener,noreferrer");
}

// -- ortak üst şerit: tercihler (dil, yazı boyutu, karşıtlık) ------------------------------------------------
// Ortak tercih dosyasına (ArthurLegal kurulumunda KOK/veri/arayuz-tercihleri.json) yazılır; öteki arayüzler sonraki
// açılışta okur. Bu tarayıcıdaki kopya yalnız ilk boyamayı hızlandırır.
const TERCIH = { dil: "tr", yazi: "normal", karsitlik: false, gorulen_yenilik: null };
const SERIT = { bilgi: null, sonuc: null, hal: "bos", hata: "", donus: null, izleme: null, izlemeBasi: 0 };

function yerelTercih() {
  try { return JSON.parse(localStorage.getItem("am.tercih") || "{}") || {}; } catch { return {}; }
}
function gorunumUygula() {
  const kok = document.documentElement;
  kok.dataset.yazi = TERCIH.yazi;
  if (TERCIH.karsitlik) kok.dataset.karsitlik = "acik"; else delete kok.dataset.karsitlik;
  document.querySelectorAll(".yazi-secimi [data-yazi]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.yazi === TERCIH.yazi)));
  $("karsitlik-sec").checked = TERCIH.karsitlik;
  try { localStorage.setItem("am.tercih", JSON.stringify({ dil: TERCIH.dil, yazi: TERCIH.yazi, karsitlik: TERCIH.karsitlik })); } catch { /* yalnız bu sekme */ }
}
async function tercihDegistir(degisiklik) {
  Object.assign(TERCIH, degisiklik);
  gorunumUygula();
  try {
    const gelen = await api("POST", "/api/serit/tercih", degisiklik);
    TERCIH.gorulen_yenilik = gelen.gorulen_yenilik;
  } catch { /* kaydedilemedi: seçim bu tarayıcıda kalır */ }
}
async function tercihleriAl(gelen) {
  if (!gelen) return;
  const dilDegisti = gelen.dil !== DIL.secili;
  Object.assign(TERCIH, gelen);
  gorunumUygula();
  if (dilDegisti && await DIL.sec(gelen.dil)) yenidenCiz();
}

document.querySelectorAll(".yazi-secimi [data-yazi]").forEach((b) => b.addEventListener("click", () => tercihDegistir({ yazi: b.dataset.yazi })));
$("karsitlik-sec").addEventListener("change", (o) => tercihDegistir({ karsitlik: o.target.checked }));
document.querySelectorAll(".dil-secimi [data-dil]").forEach((b) => b.addEventListener("click", async () => {
  const d = b.dataset.dil;
  TERCIH.dil = d;
  if (await DIL.sec(d)) yenidenCiz();
  tercihDegistir({ dil: d });
}));
// Başka bir ArthurLegal arayüzünde değişen tercih, sayfa odak alınca okunur.
window.addEventListener("focus", () => { api("GET", "/api/serit").then((b) => tercihleriAl(b.tercihler)).catch(() => {}); });

// -- açılır paneller (durum, güncelleme, görünüm, yardım): Esc kapatır, dışarı tıklamak kapatır -----------------
const ACILIRLAR = [["durum-dugme", "durum-panel"], ["guncelle-dugme", "guncelle-panel"], ["gorunum-dugme", "gorunum-panel"],
  ["yardim-dugme", "yardim-panel"]];
function panelAc(dugmeId, ac = true) {
  for (const [d, p] of ACILIRLAR) {
    const acik = ac && d === dugmeId;
    $(p).hidden = !acik;
    $(d).setAttribute("aria-expanded", String(acik));
  }
  if (ac) {
    const panel = $(ACILIRLAR.find(([d]) => d === dugmeId)[1]);
    const ilk = panel.querySelector("button, [href], input");
    if (ilk && dugmeId !== "durum-dugme") ilk.focus();
  }
}
function panelKapat() { panelAc(null, false); }
const panelAcikMi = (dugmeId) => $(dugmeId).getAttribute("aria-expanded") === "true";
for (const [d] of ACILIRLAR) {
  if (d === "guncelle-dugme") continue;
  $(d).addEventListener("click", () => panelAc(d, !panelAcikMi(d)));
}
document.addEventListener("keydown", (o) => {
  if (o.key !== "Escape") return;
  const acik = ACILIRLAR.find(([d]) => panelAcikMi(d));
  if (acik) { panelKapat(); $(acik[0]).focus(); }
});
document.addEventListener("click", (o) => {
  if (!o.target.closest || !o.target.closest(".serit-oge")) panelKapat();
});

// -- durum noktası: yerel sunucu + Claude Desktop kaydı. Ölçülemeyen şey "bağlı" gösterilmez. ------------------
function durumNoktasi(d, hata) {
  let renk = "gri";
  let ad = cev("Çevrimdışı");
  let aciklama = cev("Yerel sunucuya ulaşılamıyor. Claude Desktop'u ya da ArthurMask kısayolunu açın.");
  if (hata === 401) {
    renk = "sari"; ad = cev("Kısıtlı");
    aciklama = cev("Yerel sunucu çalışıyor ama bu tarayıcı tanınmadı; ArthurMask'i kısayolundan açın.");
  } else if (d && d.kopru) {
    renk = "yesil"; ad = cev("Bağlı");
    aciklama = cev("Yerel sunucu çalışıyor; Claude Desktop ArthurMask'e bağlı.");
  } else if (d && d.claude_kayitli) {
    renk = "sari"; ad = cev("Kısıtlı");
    aciklama = cev("Yerel sunucu çalışıyor; ArthurMask Claude Desktop'a kayıtlı ama Claude şu an bağlı değil. Claude Desktop'u açın.");
  } else if (d) {
    renk = "sari"; ad = cev("Kısıtlı");
    aciklama = cev("Yerel sunucu çalışıyor; ArthurMask Claude Desktop'a kayıtlı değil. ArthurMask kurulumunu yeniden çalıştırın.");
  }
  const dugme = $("durum-dugme");
  dugme.className = `serit-dugme durum-dugme ${renk}`;
  $("durum-metni").textContent = ad;
  dugme.setAttribute("aria-label", `${ad}: ${aciklama}`);
  $("durum-aciklama").textContent = aciklama;
}

// -- güncelleme düğmesi ---------------------------------------------------------------------------------------
// Hâller: bos · denetleniyor · guncel (5 sn sonra bos) · yeni (altın nokta, panel) · guncelleniyor · bitti · hata.
const MAC = () => (SERIT.bilgi ? SERIT.bilgi.platform === "darwin" : /Mac/.test(navigator.platform));

function seritCiz() {
  const s = SERIT.sonuc;
  const dugme = $("guncelle-dugme");
  const metin = $("guncelle-metin");
  const hal = SERIT.hal;
  dugme.disabled = hal === "denetleniyor";
  dugme.classList.toggle("donuyor", hal === "denetleniyor" || hal === "guncelleniyor");
  $("guncelle-rozet").hidden = hal !== "yeni";
  let yazi = cev("Güncellemeleri denetle");
  let etiket = yazi;
  if (hal === "denetleniyor") yazi = etiket = cev("Denetleniyor…");
  else if (hal === "guncel") yazi = etiket = cev("Güncelsiniz (v{0}) · son denetim {1}", s.kurulu, s.denetim ? saat(s.denetim) : "—");
  else if (hal === "yeni") { yazi = cev("Yeni sürüm: v{0}", s.son); etiket = cev("Yeni sürüm var: v{0}. Ayrıntılar için açın.", s.son); }
  else if (hal === "guncelleniyor") yazi = etiket = cev("Güncelleniyor…");
  else if (hal === "bitti") yazi = etiket = cev("Yeni sürüm indi");
  else if (hal === "hata") { yazi = cev("Denetlenemedi"); etiket = cev("Denetlenemedi: internet yok ya da GitHub yanıt vermedi"); }
  else if (SERIT.bilgi && !SERIT.bilgi.al_kurulu) etiket = `${yazi} · ${cev("ArthurLegal kurulumu bulunamadı")}`;
  metin.textContent = yazi;
  dugme.setAttribute("aria-label", etiket);
  dugme.title = etiket;
  panelIcerigi();
}

function panelIcerigi() {
  const s = SERIT.sonuc || {};
  const baslik = $("guncelle-baslik");
  const govde = [];
  const kapat = el("button", { type: "button", sinif: "ikincil", onclick: () => { panelKapat(); $("guncelle-dugme").focus(); } }, cev("Kapat"));
  const eylem = (...d) => el("div", { sinif: "eylem-satiri" }, ...d, kapat);
  const alYok = s.kaynak === "mask";
  if (SERIT.hal === "yeni") {
    baslik.textContent = cev("v{0} hazır", s.son);
    const maddeler = (s.yenilikler && (s.yenilikler[DIL.secili] || s.yenilikler.tr)) || [];
    if (maddeler.length) govde.push(el("ul", {}, maddeler.slice(0, 5).map((m) => el("li", {}, m))));
    if (alYok) {
      govde.push(el("p", {}, cev("ArthurLegal kurulumu bulunamadı; ArthurMask kendi sürüm sayfasına baktı.")),
        el("p", {}, MAC()
          ? cev("Yeni disk görüntüsündeki ArthurMask'i Uygulamalar klasörüne sürükleyip eskisinin yerine koyun; dosyalarınız korunur.")
          : cev("Yeni kurulum dosyasını eskisinin üzerine kurun; dosyalarınız korunur.")));
      govde.push(eylem(el("button", { type: "button", onclick: () => disAc(s.sayfa) }, cev("Sürüm sayfasını aç"))));
    } else {
      govde.push(eylem(
        el("button", { type: "button", onclick: simdiGuncelle }, cev("Şimdi güncelle")),
        el("button", { type: "button", sinif: "ikincil", onclick: () => disAc(s.kurulum) }, cev("Kurulum sayfasını aç"))));
    }
  } else if (SERIT.hal === "guncelleniyor") {
    baslik.textContent = cev("Güncelleniyor…");
    govde.push(el("p", {}, cev("Güncelleniyor… pencereyi kapatabilirsiniz")), eylem());
  } else if (SERIT.hal === "bitti") {
    baslik.textContent = cev("Yeni sürüm indi");
    govde.push(el("p", {}, MAC()
      ? cev("Yeni sürüm indi; Claude Desktop'u yeniden açınca devreye girer")
      : cev("Yeni sürüm indi; Claude Desktop kapanınca kurulacak")));
    if (s.guncelleme && s.guncelleme.son_sonuc) govde.push(el("p", { sinif: "not" }, s.guncelleme.son_sonuc));
    govde.push(eylem());
  } else if (SERIT.hal === "hata") {
    baslik.textContent = cev("Denetlenemedi");
    govde.push(el("p", {}, cev("Denetlenemedi: internet yok ya da GitHub yanıt vermedi")));
    if (SERIT.hata) govde.push(el("p", { sinif: "not" }, SERIT.hata));
    govde.push(eylem(
      el("button", { type: "button", onclick: () => denetle(true) }, cev("Tekrar dene")),
      el("button", { type: "button", sinif: "ikincil", onclick: () => disAc(s.kurulum || (SERIT.bilgi && SERIT.bilgi.baglantilar.kurulum)) },
        cev("Elle indir"))));
  } else {
    baslik.textContent = "";
  }
  $("guncelle-icerik").replaceChildren(...govde);
}

function sonucuIsle(s, { sessiz = false } = {}) {
  SERIT.sonuc = s;
  clearTimeout(SERIT.donus);
  if (s.guncelleme && s.guncelleme.calisiyor) {
    SERIT.hal = "guncelleniyor";
    izlemeyiBaslat();
  } else if (s.durum === "yeni") {
    SERIT.hal = "yeni";
  } else if (s.durum === "hata") {
    SERIT.hal = sessiz ? "bos" : "hata";
    SERIT.hata = s.hata || "";
  } else if (sessiz) {
    SERIT.hal = "bos";
  } else {
    SERIT.hal = "guncel";
    SERIT.donus = setTimeout(() => { if (SERIT.hal === "guncel") { SERIT.hal = "bos"; seritCiz(); } }, 5000);
  }
  seritCiz();
}

async function denetle(zorla) {
  panelKapat();
  SERIT.hal = "denetleniyor";
  seritCiz();
  try {
    const s = await api("POST", "/api/serit/denetle", { zorla });
    sonucuIsle(s);
    if (SERIT.hal === "hata") panelAc("guncelle-dugme");
  } catch (h) {
    SERIT.hal = "hata";
    SERIT.hata = h.message;
    seritCiz();
    panelAc("guncelle-dugme");
  }
}

$("guncelle-dugme").addEventListener("click", () => {
  if (SERIT.hal === "bos" || SERIT.hal === "guncel") {
    // ArthurLegal yoksa da ArthurMask'in kendi sürüm sayfasına bakılır; kurulum sayfası yeni sürüm panelinden açılır.
    denetle(true);
    return;
  }
  if (SERIT.hal !== "denetleniyor") panelAc("guncelle-dugme", !panelAcikMi("guncelle-dugme"));
});

async function simdiGuncelle() {
  try {
    const r = await api("POST", "/api/serit/guncelle");
    if (!r.basladi && r.neden !== "calisiyor") throw new Error(cev("Güncelleyici başlatılamadı."));
    SERIT.hal = "guncelleniyor";
    seritCiz();
    izlemeyiBaslat();
  } catch (h) {
    SERIT.hal = "hata";
    SERIT.hata = h.message;
    seritCiz();
  }
}

// 3 sn arayla, güncelleyici bitene dek (en çok 15 dk).
function izlemeyiBaslat() {
  if (SERIT.izleme) return;
  SERIT.izlemeBasi = Date.now();
  const adim = async () => {
    let s = null;
    try { s = await api("POST", "/api/serit/denetle", { zorla: false }); } catch { /* bir sonraki adımda yeniden */ }
    if (s && !(s.guncelleme && s.guncelleme.calisiyor)) {
      SERIT.izleme = null;
      SERIT.sonuc = s;
      const sonuc = (s.guncelleme && s.guncelleme.son_sonuc) || "";
      if (/(^|; )hata/.test(sonuc)) { SERIT.hal = "hata"; SERIT.hata = sonuc; }
      else if (s.guncelleme && s.guncelleme.yeniden_baslat) SERIT.hal = "bitti";
      else if (s.durum === "yeni") SERIT.hal = "yeni";
      else { sonucuIsle(s); return; }
      seritCiz();
      return;
    }
    if (Date.now() - SERIT.izlemeBasi > 15 * 60 * 1000) {
      SERIT.izleme = null;
      SERIT.hal = "hata";
      SERIT.hata = cev("Güncelleme 15 dakikada bitmedi.");
      seritCiz();
      return;
    }
    SERIT.izleme = setTimeout(adim, 3000);
  };
  SERIT.izleme = setTimeout(adim, 3000);
}

// -- yardım menüsü: yenilikler, sistem bilgisi, kullanıcı rehberi --------------------------------------------
const surumDemeti = (s) => (typeof s === "string" ? s.split(".").map((p) => parseInt(p, 10) || 0) : []);
function surumKucuk(a, b) {
  const x = surumDemeti(a);
  const y = surumDemeti(b);
  for (let i = 0; i < Math.max(x.length, y.length); i += 1) {
    if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) < (y[i] || 0);
  }
  return false;
}

async function yenilikleriGoster({ ilkAcilis = false } = {}) {
  let y;
  try { y = await api("GET", "/api/serit/yenilikler"); } catch { return; }
  const bolumler = [];
  const liste = (m) => (m && (m[DIL.secili] || m.tr)) || [];
  if (liste(y.mask.maddeler).length) {
    bolumler.push(el("section", { sinif: "yenilik-bolum" }, el("h3", {}, `ArthurMask v${y.mask.surum}`),
      el("ul", {}, liste(y.mask.maddeler).map((m) => el("li", {}, m)))));
  }
  if (y.al && liste(y.al.maddeler).length) {
    bolumler.push(el("section", { sinif: "yenilik-bolum" }, el("h3", {}, `ArthurLegal v${y.al.surum}`),
      el("ul", {}, liste(y.al.maddeler).map((m) => el("li", {}, m)))));
  }
  if (!bolumler.length) {
    if (ilkAcilis) return;
    bolumler.push(el("p", { sinif: "not" }, cev("Bu sürüm için yenilik notu yok.")));
  }
  $("yenilikler-icerik").replaceChildren(...bolumler);
  if (!$("yenilikler").open) $("yenilikler").showModal();
}
$("yenilikler-ac").addEventListener("click", () => { panelKapat(); yenilikleriGoster(); });
$("yenilikler").addEventListener("close", () => {
  const surum = SERIT.bilgi && SERIT.bilgi.surum;
  if (surum && (!TERCIH.gorulen_yenilik || surumKucuk(TERCIH.gorulen_yenilik, surum))) tercihDegistir({ gorulen_yenilik: surum });
});

function sistemMetni(t) {
  const satirlar = [cev("ArthurLegal sistem bilgisi"), cev("Arayüz: {0}", `${t.arayuz} v${t.surum}`)];
  const al = t.al;
  if (al && al.surumler) {
    const s = al.surumler;
    const parcalar = [`ArthurLegal v${s.al || "?"}`];
    if (s.masa) parcalar.push(`masa ${s.masa}`);
    if (s.tapu) parcalar.push(`Tapu ${s.tapu}`);
    if (s.uyap) parcalar.push(`UYAP ${s.uyap}`);
    if (s.mask) parcalar.push(`ArthurMask ${s.mask}`);
    satirlar.push(parcalar.join(" · "));
  } else {
    satirlar.push(cev("ArthurLegal kurulumu bulunamadı"));
  }
  satirlar.push(cev("İşletim sistemi: {0} ({1})", (al && al.isletim_sistemi) || t.isletim_sistemi, (al && al.mimari) || t.mimari));
  satirlar.push(cev("Dil: {0} · Modüller: {1}", (al && al.dil) || DIL.secili, (al && (al.moduller || []).join(", ")) || "—"));
  satirlar.push(cev("Son denetim: {0} · {1}", (al && al.son_denetim) || "—", (al && al.son_sonuc) || "—"));
  const hatalar = (al && al.son_hatalar) || [];
  satirlar.push(cev("Son hatalar: {0}", hatalar.length ? `\n${hatalar.join("\n")}` : cev("(yok)")));
  return satirlar.join("\n");
}
$("sistem-kopyala").addEventListener("click", async () => {
  const bildirim = $("sistem-bildirim");
  bildirim.textContent = cev("Hazırlanıyor…");
  try {
    const t = await api("GET", "/api/serit/tani");
    await navigator.clipboard.writeText(sistemMetni(t));
    bildirim.textContent = cev("Sistem bilgisi kopyalandı.");
  } catch {
    bildirim.textContent = cev("Kopyalanamadı.");
  }
  setTimeout(() => { bildirim.textContent = ""; }, 3000);
});
$("rehber-dis").addEventListener("click", () => {
  panelKapat();
  disAc((SERIT.bilgi && SERIT.bilgi.baglantilar.rehber) || "https://github.com/beerbottle90/ArthurLegal/tree/main/docs/rehber");
});

async function seritBaslat() {
  try {
    SERIT.bilgi = await api("GET", "/api/serit");
  } catch { seritCiz(); return; }
  await tercihleriAl(SERIT.bilgi.tercihler);
  seritCiz();
  // Açılışta sessiz okuma (önbellek süresi içinde ağa çıkılmaz); yalnız yeni sürüm ya da süren güncelleme gösterilir.
  api("POST", "/api/serit/denetle", { zorla: false }).then((s) => sonucuIsle(s, { sessiz: true })).catch(() => {});
  // Güncellemeden sonraki ilk açılışta yenilikler bir kez gösterilir.
  const g = SERIT.bilgi.tercihler.gorulen_yenilik;
  if (!g || surumKucuk(g, SERIT.bilgi.surum)) yenilikleriGoster({ ilkAcilis: true });
}

// -- durum, menü ve kurtarma anahtarı -----------------------------------------------------------
async function durumuYenile() {
  const koruma = $("koruma-durumu");
  try {
    const d = await api("GET", "/api/durum");
    if (d.platform === "darwin" && !durum.macos) {
      durum.macos = true;
      document.querySelectorAll("[data-macos]").forEach((e) => { e.dataset.cev = e.dataset.macos; });
      DIL.sabitler();
    }
    durumNoktasi(d);
    koruma.hidden = false;
    if (!d.motor_hazir) {
      koruma.className = "durum yukleniyor";
      koruma.textContent = cev("Koruma hazırlanıyor…");
      koruma.removeAttribute("title");
    } else {
      const tam = d.semantik && d.ocr;
      koruma.className = "durum " + (tam ? "hazir" : "yukleniyor");
      koruma.textContent = tam ? cev("Tam koruma") : cev("Temel koruma");
      koruma.title = [cev("Kurallar"), d.semantik ? cev("yapay zekâ ad tespiti") : null, d.ocr ? cev("taranmış belge okuma") : null]
        .filter(Boolean).join(" + ");
    }
    $("kurtarma-rozet").hidden = d.kurtarma_saklandi;
    $("kurtarma-saklandi").hidden = !d.kurtarma_saklandi;
  } catch (h) {
    durumNoktasi(null, h.durum);
    koruma.hidden = true;
  }
}

$("rehber-ac").addEventListener("click", () => $("rehber").showModal());
$("kurtarma-ac").addEventListener("click", () => $("kurtarma").showModal());
$("kurtarma").addEventListener("close", () => {
  $("kurtarma-kod").textContent = "";
  $("kurtarma-kod").hidden = true;
  $("kurtarma-goster").hidden = false;
  $("kurtarma-kopyala").hidden = true;
  $("kurtarma-onay").hidden = true;
});
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
  $("kurtarma").close();
  await durumuYenile();
});

// -- dosyalar ---------------------------------------------------------------------------------
async function dosyalariYukle() {
  const { dosyalar, aktif } = await api("GET", "/api/dosyalar");
  durum.aktif = durum.yeniDosya ? null : aktif;
  const secili = durum.aktif;
  $("dosya-listesi").replaceChildren(...dosyalar.map((d) => el("li", {},
    el("button", {
      sinif: "dosya" + (d.klasor === secili ? " aktif" : ""), type: "button",
      "aria-current": d.klasor === secili ? "true" : false,
      onclick: () => dosyaSec(d.klasor),
    }, d.ad, el("small", {}, cev("{0} belge · {1} cevap", d.belge_sayisi, d.cevap_sayisi))),
  )));
  if (!dosyalar.length) {
    $("dosya-listesi").replaceChildren(el("li", { sinif: "not" }, cev("Henüz dosya yok. İlk belgeyi bırakın.")));
  }
  $("yeni-dosya").classList.toggle("aktif", !secili);
  birakAlaniniGuncelle();
  $("calisma").hidden = !secili;
  if (secili) await calismayiYenile();
}

function birakAlaniniGuncelle() {
  const yeni = !durum.aktif;
  $("birak-baslik").textContent = yeni ? cev("Yeni dosya: ilk belgeyi buraya bırakın") : cev("Belgeyi buraya bırakın");
  if (!birak.classList.contains("isleniyor") && !birak.classList.contains("hatali")) {
    $("birak-ipucu").textContent = yeni ? cev("Dosya adı belgeden alınır · {0}", ipucu()) : ipucu();
  }
}

async function dosyaSec(klasor) {
  durum.yeniDosya = false;
  await api("POST", "/api/aktif", { klasor });
  durum.acikInceleme = null;
  durum.belgeImza = durum.cevapImza = durum.incelemeImza = durum.gidenImza = undefined;
  $("denetim-sonucu").hidden = true;
  await dosyalariYukle();
}

$("yeni-dosya").addEventListener("click", async () => {
  durum.yeniDosya = true;
  durum.acikInceleme = null;
  $("denetim-sonucu").hidden = true;
  await dosyalariYukle();
  birak.focus();
});

/** "nda_final_13092026.docx" → "nda final 13092026" */
function belgedenDosyaAdi(ad) {
  return ad.replace(/\.[^.]+$/, "").replace(/_+/g, " ").replace(/\s+/g, " ").trim().slice(0, 80) || cev("Adsız dosya");
}

// -- belge yükleme ---------------------------------------------------------------------------
const birak = $("birak");
birak.addEventListener("click", () => $("dosya-sec").click());
birak.addEventListener("keydown", (o) => { if (o.key === "Enter" || o.key === " ") { o.preventDefault(); $("dosya-sec").click(); } });
birak.addEventListener("dragover", (o) => { o.preventDefault(); birak.classList.add("uzerinde"); });
birak.addEventListener("dragleave", () => birak.classList.remove("uzerinde"));
birak.addEventListener("drop", (o) => { o.preventDefault(); birak.classList.remove("uzerinde"); yukle([...o.dataTransfer.files]); });
$("dosya-sec").addEventListener("change", (o) => { yukle([...o.target.files]); o.target.value = ""; });

async function yukle(dosyalar) {
  if (!dosyalar.length) return;
  birak.classList.remove("hatali");
  birak.classList.add("isleniyor");
  const ipucuAlani = $("birak-ipucu");
  let hataVar = false;
  try {
    if (!durum.aktif) {
      const { klasor } = await api("POST", "/api/dosyalar", { ad: belgedenDosyaAdi(dosyalar[0].name), benzersiz: true });
      durum.yeniDosya = false;
      durum.aktif = klasor;
      durum.belgeImza = durum.cevapImza = durum.incelemeImza = durum.gidenImza = undefined;
    }
    for (const dosya of dosyalar) {
      ipucuAlani.textContent = cev("{0} maskeleniyor…", dosya.name);
      const sonuc = await api("POST", `/api/dosyalar/${encodeURIComponent(durum.aktif)}/belgeler`,
        await dosya.arrayBuffer(), { "X-Dosya-Adi": encodeURIComponent(dosya.name) });
      if (sonuc.durum !== "hazir") { durum.acikInceleme = sonuc.id; durum.kaydir = true; }
    }
  } catch (hata) {
    hataVar = true;
    ipucuAlani.textContent = cev("Olmadı: {0}", hata.message);
  } finally {
    birak.classList.remove("isleniyor");
    if (hataVar) birak.classList.add("hatali");
    await dosyalariYukle();
  }
}

// -- belgeler ve inceleme ------------------------------------------------------------------------
async function calismayiYenile() {
  const k = encodeURIComponent(durum.aktif);
  const [{ belgeler }, { cevaplar }, gidenler] = await Promise.all([
    api("GET", `/api/dosyalar/${k}/belgeler`),
    api("GET", `/api/dosyalar/${k}/cevaplar`),
    api("GET", `/api/dosyalar/${k}/gidenler`),
  ]);
  // Yalnız veri değiştiğinde yeniden çiz: açık incelemedeki seçimler, gerekçe ve açık ayrıntılar kaybolmasın.
  const belgeImza = JSON.stringify(belgeler.map((b) => [b.id, b.durum, b.etiket_sayisi]));
  const cevapImza = JSON.stringify(cevaplar.map((c) => [c.ad, c.cozulen]));
  const gidenImza = JSON.stringify([gidenler.toplam_yanit, gidenler.kayitlar[0] && gidenler.kayitlar[0].zaman]);
  const incelenen = belgeler.find((b) => b.id === durum.acikInceleme);
  const incelemeImza = incelenen ? `${incelenen.id}:${incelenen.durum}:${incelenen.etiket_sayisi}` : "";
  durum.belgeler = belgeler;
  durum.cevaplar = cevaplar;
  durum.gidenler = gidenler;
  if (belgeImza !== durum.belgeImza) { durum.belgeImza = belgeImza; belgeleriCiz(); }
  if (cevapImza !== durum.cevapImza) { durum.cevapImza = cevapImza; cevaplariCiz(); }
  if (gidenImza !== durum.gidenImza) { durum.gidenImza = gidenImza; gidenleriCiz(); }
  if (incelemeImza !== durum.incelemeImza) { durum.incelemeImza = incelemeImza; incelemeyiCiz(); }
}

// Etiket türü adları (KİŞİ, ŞİRKET…) maskeleme protokolünün verisidir; yalnız ekrandaki okunur özet çevrilir.
const TUR_OKUNUR = {
  "KİŞİ": cevN("{0} kişi"), "ŞİRKET": cevN("{0} şirket"), "ADRES": cevN("{0} adres"), "TELEFON": cevN("{0} telefon"),
  "EPOSTA": cevN("{0} e-posta"), "DOSYA_NO": cevN("{0} dosya no"), "DOĞUM_TARİHİ": cevN("{0} doğum tarihi"),
  "PASAPORT": cevN("{0} pasaport"), "PLAKA": cevN("{0} plaka"), "NUMARA": cevN("{0} numara"), "GİZLİ": cevN("{0} gizli ifade"),
};
function turOzeti(turler) {
  return Object.entries(turler).map(([t, n]) => (TUR_OKUNUR[t] ? cev(TUR_OKUNUR[t], n) : `${n} ${t}`)).join(", ");
}

function belgeleriCiz() {
  const hazir = durum.belgeler.find((b) => b.durum === "hazir");
  $("komut-kutusu").hidden = !hazir;
  // Claude'a yapıştırılacak komut seçili dilde yazılır; Claude her dilde anlar.
  if (hazir) $("ornek-komut").textContent = cev("ArthurMask'teki {0}'i incele", hazir.id);
  if (!durum.belgeler.length) {
    $("belge-listesi").replaceChildren(el("li", { sinif: "not" }, cev("Henüz belge yok. Yukarıdaki alana bir belge bırakın.")));
    return;
  }
  $("belge-listesi").replaceChildren(...durum.belgeler.map((b) => {
    const bulgu = tutarlilikSayisi(b);
    const etiketler = b.etiket_sayisi ? cev("{0} etiket: {1}", b.etiket_sayisi, turOzeti(b.turler)) : cev("{0} etiket", 0);
    return el("li", { sinif: "belge" },
      el("span", { sinif: "ad" }, `${b.kaynak_ad} `, el("span", { sinif: `cip ${b.durum}` }, cev(DURUM_ADI[b.durum])),
        b.surum ? el("span", { sinif: "cip surum" }, b.surum.rol === "yeni" ? cev("Yeni sürüm") : cev("Özgün sürüm")) : null),
      el("span", { sinif: "meta" }, `${b.id} · ${tarih(b.olusturma)} · ${etiketler}`),
      el("span", { sinif: "eylemler" },
        bulgu ? el("button", { type: "button", sinif: "ikincil", onclick: () => incelemeAc(b, "tutarlilik") },
          cev("Tutarlılık · {0}", bulgu)) : null,
        el("button", { type: "button", sinif: b.durum === "hazir" ? "ikincil" : "", onclick: () => incelemeAc(b) },
          b.durum === "hazir" ? cev("Önizle") : cev("İncele")),
        el("button", { type: "button", sinif: "ikincil", "aria-label": cev("{0} sil", b.kaynak_ad), onclick: () => belgeSil(b.id) }, cev("Sil"))),
    );
  }));
}

const tutarlilikSayisi = (b) => (b.tutarlilik && b.tutarlilik.ozet ? b.tutarlilik.ozet.toplam : 0);

function incelemeAc(belge, bolum) {
  durum.acikInceleme = belge.id;
  durum.incelemeImza = `${belge.id}:${belge.durum}:${belge.etiket_sayisi}`;
  durum.kaydir = bolum || true;
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
  const bolumler = [el("p", {}, el("strong", {}, belge.kaynak_ad), " · ", el("span", { sinif: `cip ${belge.durum}` }, cev(DURUM_ADI[belge.durum])))];

  for (const uyari of belge.uyarilar) bolumler.push(el("p", { sinif: "uyari" }, `⚠ ${cevS(uyari)}`));
  if (belge.yeniden_yukleme_gerekli) {
    bolumler.push(el("p", { sinif: "hata-mesaji" }, cev("Bu belgenin inceleme bilgisi bu oturumda yok. Belgeyi silip yeniden bırakın.")));
  }

  let gerekce = null;
  if (bekliyor && belge.kirmizi_hat.length) {
    gerekce = el("textarea", { rows: "2", placeholder: cev("Neden yine de gönderiyorsunuz? (kayda geçer)"), "aria-label": cev("Kırmızı hat gerekçesi") });
    bolumler.push(el("div", { sinif: "kirmizi-kutu" },
      el("strong", {}, cev("Kırmızı hat — maskelense de içerik gizlenmez")),
      el("ul", {}, belge.kirmizi_hat.map((k) => el("li", {}, cev("{0} (satır {1})", cevS(k.kategori), k.satirlar.slice(0, 8).join(", "))))),
      gerekce));
  }

  const secimler = [];
  if (bekliyor && belge.supheli.length) {
    bolumler.push(el("h3", {}, cev("Emin olunamayanlar ({0}) — maskelensin mi?", belge.supheli.length)));
    for (const aday of belge.supheli) {
      const ad = `aday-${belge.id}-${aday.sira}`;
      const maskele = el("input", { type: "radio", name: ad, value: "maskele", checked: "checked" });
      const birakRadyo = el("input", { type: "radio", name: ad, value: "birak" });
      secimler.push({ sira: aday.sira, maskele });
      const i = aday.baglam.indexOf(aday.metin);
      const baglam = i < 0 ? [aday.baglam] : [aday.baglam.slice(0, i), el("mark", {}, aday.metin), aday.baglam.slice(i + aday.metin.length)];
      bolumler.push(el("div", { sinif: "aday" },
        el("div", { sinif: "secim" }, el("label", {}, maskele, cev("Maskele")), el("label", {}, birakRadyo, cev("Açık bırak"))),
        el("div", {}, el("strong", {}, aday.metin), " ", el("span", { sinif: "tur" }, aday.tur)),
        el("div", { sinif: "baglam" }, "…", baglam, "…")));
    }
  }

  bolumler.push(el("div", { sinif: "eylem-satiri sol" },
    el("button", { type: "button", sinif: belge.ocr ? "" : "ikincil", onclick: () => maskeliKopyaAc(belge) },
      belge.ocr ? cev("Maskeli sayfaları kontrol et (PDF)") : cev("Maskeli kopyayı aç"))));
  bolumler.push(el("h3", {}, cev("Claude'un göreceği metin")));
  bolumler.push(el("div", { sinif: "onizleme", tabindex: "0" }, etiketliMetin(belge.maskeli_metin)));
  const tutarlilikKutusu = tutarlilikBolumu(belge);
  if (tutarlilikKutusu) bolumler.push(tutarlilikKutusu);

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
    }, cev("Onayla — Claude'a hazırla")));
  }
  eylemler.append(el("button", { type: "button", sinif: "ikincil", onclick: () => { durum.acikInceleme = null; durum.incelemeImza = ""; incelemeyiCiz(); } }, cev("Kapat")));
  bolumler.push(hata, eylemler);
  $("inceleme-icerik").replaceChildren(...bolumler);
  if (durum.kaydir) {
    const hedef = durum.kaydir === "tutarlilik" && tutarlilikKutusu ? tutarlilikKutusu : panel;
    durum.kaydir = false;
    hedef.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

// -- iç tutarlılık raporu (tam hâli, gerçek adlarla; yalnız bu bilgisayardan okunur) ---------------------
const ONEM_SINIFI = { "yüksek": "kirmizi_hat", "orta": "onay_bekliyor", "düşük": "" };
const ONEM_ADI = { "yüksek": cevN("yüksek"), "orta": cevN("orta"), "düşük": cevN("düşük") };
durum.tutarlilik = {};
// "Madde 4 · Tablo 1, satır 2, sütun 1 (TR)" parça parça çevrilir.
const yerMetni = (yer) => (yer || "").split(" · ").map(cevS).join(" · ");

function tutarlilikBolumu(belge) {
  const rapor = belge.tutarlilik;
  if (!rapor) return null;
  const kutu = el("section", { sinif: "tutarlilik", "aria-label": cev("İç tutarlılık denetimi") });
  kutu.append(el("h3", {}, cev("İç tutarlılık denetimi")));
  if (rapor.hata) {
    kutu.append(el("p", { sinif: "not ust-bosluksuz" }, cevS(rapor.hata)));
    return kutu;
  }
  const o = rapor.ozet;
  kutu.append(el("p", { sinif: "not ust-bosluksuz" }, o.toplam
    ? cev("{0} bulgu: {1} yüksek, {2} orta, {3} düşük önem. Kurallarla bulundu; her birini metinde kontrol edin.", o.toplam, o.yuksek, o.orta, o.dusuk)
    : cev("Tanımlı terimler, iç atıflar, taraf unvanları ve çift dilli sütunlarda tutarsızlık bulunmadı.")));
  const liste = el("ol", { sinif: "tutarlilik-listesi" });
  const notlar = el("div");
  kutu.append(liste, notlar);
  if (belge.durum === "hazir") {
    const komut = cev("ArthurMask'teki {0} için tutarlılık raporunu yorumla ve düzeltme öner", belge.id);
    kutu.append(el("div", { sinif: "komut" }, el("span", {}, cev("Claude'a:")), el("code", {}, komut),
      el("button", { type: "button", sinif: "ikincil", onclick: (e) => kopyala(komut, e.currentTarget) }, cev("Kopyala"))));
  }
  if (!o.toplam && !(rapor.notlar || []).length) return kutu;
  const anahtar = `${belge.id}:${belge.etiket_sayisi}:${o.toplam}`;
  const ciz = (tam) => {
    liste.replaceChildren(...tam.bulgular.map((b) => el("li", { sinif: "tutarlilik-bulgu" },
      el("div", {}, el("span", { sinif: `cip ${ONEM_SINIFI[b.onem] || ""}` }, ONEM_ADI[b.onem] ? cev(ONEM_ADI[b.onem]) : b.onem), " ",
        el("strong", {}, cevS(b.kural))),
      el("div", {}, cevS(b.aciklama)),
      el("div", { sinif: "meta" }, yerMetni(b.yer)),
      b.alinti ? el("div", { sinif: "onizleme alinti" }, b.alinti) : null)));
    notlar.replaceChildren(...(tam.notlar || []).map((n) => el("p", { sinif: "not" }, cevS(n))));
  };
  if (durum.tutarlilik[belge.id] && durum.tutarlilik[belge.id].anahtar === anahtar) {
    ciz(durum.tutarlilik[belge.id].rapor);
  } else {
    liste.append(el("li", { sinif: "not" }, cev("Rapor açılıyor…")));
    api("GET", `/api/dosyalar/${encodeURIComponent(durum.aktif)}/belgeler/${belge.id}/tutarlilik`)
      .then((tam) => { durum.tutarlilik[belge.id] = { anahtar, rapor: tam }; ciz(tam); })
      .catch((h) => liste.replaceChildren(el("li", { sinif: "hata-mesaji" }, h.message)));
  }
  return kutu;
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
function cevaplariCiz() {
  const liste = $("cevap-listesi");
  if (!durum.cevaplar.length) {
    liste.replaceChildren(el("li", { sinif: "not" }, cev("Claude bir taslak teslim ettiğinde ya da belgeyi revize ettiğinde burada gerçek adlarla görünür.")));
    return;
  }
  liste.replaceChildren(...durum.cevaplar.map(cevapKarti));
}

function karsilastirmaKarti(c) {
  const uyarilar = (c.uyarilar || []).map((u) => el("p", { sinif: "uyari" }, `⚠ ${cevS(u)}`));
  return el("li", { sinif: "cevap" },
    el("span", { sinif: "ad" }, cevS(c.baslik), " ", el("span", { sinif: "cip hazir" }, cev("Sürüm karşılaştırması"))),
    el("span", { sinif: "meta" }, cev("{0} · {1} (özgün) → {2} (yeni sürüm) · Word, izli değişiklik", tarih(c.olusturma), c.ozgun, c.yeni)),
    el("span", { sinif: "eylemler" },
      el("button", { type: "button", onclick: () => cevapAc(c, false) }, cev("Word'de aç (izli değişiklikler)")),
      el("button", { type: "button", sinif: "ikincil", onclick: () => cevapAc(c, true) }, cev("Klasörde göster"))),
    el("div", { sinif: "cevap-alt" }, ...uyarilar, el("p", { sinif: "not ust-bosluksuz" }, cevS(c.acik_metin))),
  );
}

function cevapKarti(c) {
  if (c.tur === "karsilastirma") return karsilastirmaKarti(c);
  const revizyon = c.tur === "revizyon";
  const metinKutusu = el("div", { sinif: "metin onizleme", tabindex: "0" });
  const sekmeler = el("div", { sinif: "sekmeler", role: "tablist", "aria-label": cev("Görünüm") });
  const secenekler = [["acik", cev("Gerçek adlarla")], ["maskeli", cev("Claude'daki hâli")]];
  const dugmeler = secenekler.map(([g, ad]) => el("button", {
    type: "button", role: "tab", sinif: "sekme",
    onclick: () => { durum.cevapGorunum[c.ad] = g; sekmeCiz(); },
  }, ad));
  sekmeler.append(...dugmeler);
  const esitNot = el("span", { sinif: "not satir-ici" });
  sekmeler.append(esitNot);
  function sekmeCiz() {
    const secili = durum.cevapGorunum[c.ad] || "acik";
    dugmeler.forEach((d, i) => d.setAttribute("aria-selected", String(secenekler[i][0] === secili)));
    metinKutusu.replaceChildren(secili === "acik" ? c.acik_metin : etiketliMetin(c.maskeli_metin));
    esitNot.textContent = c.cozulen ? "" : cev("Bu metinde etiket yok; iki görünüm aynıdır.");
  }
  sekmeCiz();

  const meta = [`${tarih(c.olusturma)} · ${c.bicim.toUpperCase()}`];
  if (revizyon) {
    meta.push(c.izli ? cev("{0} değişiklik izli olarak işlendi", c.uygulanan) : cev("{0} değişiklik işlendi", c.uygulanan));
    if (c.sorunlar && c.sorunlar.length) meta.push(cev("{0} değişiklik uygulanamadı", c.sorunlar.length));
  }
  meta.push(cev("{0} etiket çözüldü", c.cozulen));

  const uyarilar = [];
  if (c.bilinmeyen.length) uyarilar.push(el("p", { sinif: "uyari" }, `⚠ ${cev("Kasada olmayan etiket: {0}", c.bilinmeyen.join(", "))}`));
  if (revizyon && c.sorunlar && c.sorunlar.length) {
    uyarilar.push(el("details", { sinif: "sorunlar" }, el("summary", {}, cev("Uygulanamayan değişiklikler")),
      el("ul", {}, c.sorunlar.map((s) => el("li", {}, `${s.sira}. ${cevS(s.neden)}`)))));
  }
  const acDugmesi = revizyon && c.izli ? cev("Word'de aç (izli değişiklikler)") : cev(BICIM_ADI[c.bicim] || BICIM_ADI.txt);
  return el("li", { sinif: "cevap" },
    el("span", { sinif: "ad" }, c.baslik, " ", revizyon ? el("span", { sinif: "cip hazir" }, cev("Revizyon")) : null),
    el("span", { sinif: "meta" }, meta.join(" · ")),
    el("span", { sinif: "eylemler" },
      el("button", { type: "button", onclick: () => cevapAc(c, false) }, acDugmesi),
      el("button", { type: "button", sinif: "ikincil", onclick: () => cevapAc(c, true) }, cev("Klasörde göster"))),
    el("div", { sinif: "cevap-alt" }, ...uyarilar, sekmeler, metinKutusu),
  );
}

async function cevapAc(cevap, klasorde) {
  await api("POST", `/api/dosyalar/${encodeURIComponent(durum.aktif)}/cevap-ac`, { dosya: cevap.dosya, klasorde });
}

// -- Claude'a giden ve sızıntı denetimi ----------------------------------------------------------
const ARAC_ADI = {
  mcp_belgeler: cevN("Belge listesi"), mcp_belge_getir: cevN("Belge metni"), mcp_revize: cevN("Revizyon sonucu"),
  mcp_teslim: cevN("Teslim sonucu"), mcp_surum_karsilastir: cevN("Sürüm karşılaştırma özeti"), mcp_tutarlilik: cevN("Tutarlılık raporu"),
};

function gidenleriCiz() {
  const g = durum.gidenler;
  const ozet = $("giden-ozet");
  if (!g || !g.toplam_yanit) {
    ozet.textContent = cev("Claude bu dosyadan henüz bir şey almadı. Aldığında, gönderilen her yanıtın maskeli hâli burada listelenir.");
    $("giden-listesi").replaceChildren();
    return;
  }
  ozet.textContent = `${cev("Claude'a {0} yanıt gönderildi.", g.toplam_yanit)} ${g.toplam_yakalanan
    ? cev("Çıkış kapısı {0} açık değeri göndermeden önce etiketledi.", g.toplam_yakalanan)
    : cev("Çıkış kapısında yakalanan açık değer olmadı.")}`;
  $("giden-listesi").replaceChildren(...g.kayitlar.map((k) => {
    const detay = el("details", { sinif: "giden-kayit" },
      el("summary", {},
        `${ARAC_ADI[k.arac] ? cev(ARAC_ADI[k.arac]) : k.arac} · ${tarih(k.zaman)} `,
        k.yakalanan ? el("span", { sinif: "cip onay_bekliyor" }, cev("kapıda {0} değer etiketlendi", k.yakalanan)) : null));
    detay.addEventListener("toggle", () => {
      if (detay.open && detay.childElementCount === 1) detay.append(el("div", { sinif: "onizleme" }, etiketliMetin(k.metin)));
    });
    return el("li", {}, detay);
  }));
}

$("denetle").addEventListener("click", async (o) => {
  const dugme = o.currentTarget;
  const kutu = $("denetim-sonucu");
  dugme.disabled = true;
  dugme.textContent = cev("Denetleniyor…");
  try {
    const r = await api("POST", `/api/dosyalar/${encodeURIComponent(durum.aktif)}/denetim`);
    kutu.hidden = false;
    if (r.temiz) {
      kutu.className = "denetim temiz";
      kutu.replaceChildren(
        el("strong", {}, cev("✓ Temiz")),
        el("p", {}, cev("{0} metin, kasadaki {1} gerçek değerin her birine karşı tarandı; hiçbiri bulunmadı.", r.taranan_kaynak, r.kasadaki_deger)),
        r.gunluk_var ? null : el("p", { sinif: "not" }, cev("Bu dosyada Claude'a giden yanıt kaydı yok; kayıt bu sürümle başladı.")));
    } else {
      kutu.className = "denetim bulgu";
      kutu.replaceChildren(
        el("strong", {}, cev("⚠ Açık değer bulundu")),
        el("p", {}, cev("Aşağıdaki metinlerde kasadaki gerçek değerler etiketsiz geçiyor."), " ",
          cev("\"Claude'un yazdığı metin\": Claude bu değeri bir yerden açık görmüş (sohbete yazılan ya da eklenen belge, ya da eski sürümde kaçan bir geçiş)."), " ",
          cev("\"Çıkış kapısından önce\": değer depodaki maskeli metinde duruyor, Claude'a gönderilirken etiketlenir.")),
        el("ul", { sinif: "bulgu-listesi" }, r.bulgular.map((b) => el("li", {},
          el("strong", {}, cevS(b.kaynak)),
          el("ul", {}, b.eslesmeler.map((e) => el("li", {}, el("mark", {}, e.deger), ` → ${e.etiket} · ${cev("{0} kez", e.adet)}`)))))));
    }
  } catch (h) {
    kutu.hidden = false;
    kutu.className = "denetim bulgu";
    kutu.textContent = cev("Denetim yapılamadı: {0}", h.message);
  } finally {
    dugme.disabled = false;
    dugme.textContent = cev("Sızıntı denetimi yap");
  }
});

// -- sürüm karşılaştırması --------------------------------------------------------------------------
const surum = { ozgun: null, yeni: null, rol: null };
const YUVA_IPUCU = { ozgun: cevN("Sizdeki metin — bırakın ya da seçin"), yeni: cevN("Karşı taraftan gelen — bırakın ya da seçin") };

function yuvalariCiz() {
  for (const rol of ["ozgun", "yeni"]) {
    const dosya = surum[rol];
    $(`yuva-${rol}`).classList.toggle("dolu", !!dosya);
    $(`yuva-${rol}-ad`).textContent = dosya ? dosya.name : cev(YUVA_IPUCU[rol]);
  }
  $("karsilastir-basla").disabled = !(surum.ozgun && surum.yeni);
}

function karsilastirDurumu(metin, hata = false) {
  const d = $("karsilastir-durum");
  d.textContent = metin;
  d.classList.toggle("hata-mesaji", hata);
}

function surumDosyalari(dosyalar, rol) {
  const word = dosyalar.filter((d) => /\.docx$/i.test(d.name));
  if (word.length !== dosyalar.length) karsilastirDurumu(cev("Sürüm karşılaştırması yalnız Word (.docx) dosyalarıyla yapılır."), true);
  else karsilastirDurumu("");
  if (word.length >= 2) {
    // İki dosya birlikte bırakıldı: eski tarihli olan özgün sayılır; gerekirse ⇄ ile değiştirilir.
    const [eski, yeni] = word.slice(0, 2).sort((a, b) => a.lastModified - b.lastModified);
    surum.ozgun = eski;
    surum.yeni = yeni;
    karsilastirDurumu(cev("Eski tarihli dosya özgün sayıldı; yanlışsa ⇄ ile yer değiştirin."));
  } else if (word.length === 1) {
    surum[rol || (surum.ozgun ? "yeni" : "ozgun")] = word[0];
  }
  yuvalariCiz();
}

for (const rol of ["ozgun", "yeni"]) {
  const yuva = $(`yuva-${rol}`);
  const sec = () => { surum.rol = rol; $("yuva-sec").click(); };
  yuva.addEventListener("click", sec);
  yuva.addEventListener("keydown", (o) => { if (o.key === "Enter" || o.key === " ") { o.preventDefault(); sec(); } });
  yuva.addEventListener("dragover", (o) => { o.preventDefault(); yuva.classList.add("uzerinde"); });
  yuva.addEventListener("dragleave", () => yuva.classList.remove("uzerinde"));
  yuva.addEventListener("drop", (o) => {
    o.preventDefault();
    o.stopPropagation();
    yuva.classList.remove("uzerinde");
    surumDosyalari([...o.dataTransfer.files], rol);
  });
}
$("karsilastir").addEventListener("dragover", (o) => o.preventDefault());
$("karsilastir").addEventListener("drop", (o) => { o.preventDefault(); surumDosyalari([...o.dataTransfer.files], null); });
$("yuva-sec").addEventListener("change", (o) => { surumDosyalari([...o.target.files], surum.rol); o.target.value = ""; });
$("yuva-degistir").addEventListener("click", () => {
  [surum.ozgun, surum.yeni] = [surum.yeni, surum.ozgun];
  karsilastirDurumu("");
  yuvalariCiz();
});
$("karsilastir-komut-kopyala").addEventListener("click", (o) => kopyala($("karsilastir-komut-metni").textContent, o.target));

$("karsilastir-basla").addEventListener("click", async (o) => {
  const dugme = o.currentTarget;
  const { ozgun, yeni } = surum;
  if (!ozgun || !yeni) return;
  dugme.disabled = true;
  $("karsilastir-komut").hidden = true;
  karsilastirDurumu(cev("Karşılaştırılıyor ve maskeleniyor…"));
  try {
    if (!durum.aktif) {
      const { klasor } = await api("POST", "/api/dosyalar", { ad: belgedenDosyaAdi(yeni.name), benzersiz: true });
      durum.yeniDosya = false;
      durum.aktif = klasor;
      durum.belgeImza = durum.cevapImza = durum.incelemeImza = durum.gidenImza = undefined;
    }
    const govde = new Blob([await ozgun.arrayBuffer(), await yeni.arrayBuffer()]);
    const sonuc = await api("POST", `/api/dosyalar/${encodeURIComponent(durum.aktif)}/karsilastir`, govde, {
      "X-Boyut-1": String(ozgun.size),
      "X-Dosya-Adi-1": encodeURIComponent(ozgun.name),
      "X-Dosya-Adi-2": encodeURIComponent(yeni.name),
    });
    surum.ozgun = surum.yeni = null;
    yuvalariCiz();
    const ozet = DIL.veri(String(sonuc.ozet || ""));
    let metin = cev("{0}. İzli değişiklikli Word dosyası açılıyor (Cevaplar'da da duruyor).", `${ozet[0].toUpperCase()}${ozet.slice(1)}`);
    if (!sonuc.hazir) {
      metin += ` ${cev("Claude'a özet gitmeden önce iki belgenin incelemesini tamamlayın.")}`;
      const bekleyen = [sonuc.ozgun, sonuc.yeni].find((b) => b.durum !== "hazir");
      durum.acikInceleme = bekleyen.id;
      durum.kaydir = true;
    }
    karsilastirDurumu(metin);
    $("karsilastir-komut-metni").textContent =
      cev("ArthurMask'teki {0} (özgün) ile {1} (yeni sürüm) arasındaki farkları incele; risklerini ve karşı önerini yaz", sonuc.ozgun.id, sonuc.yeni.id);
    $("karsilastir-komut").hidden = false;
    await api("POST", `/api/dosyalar/${encodeURIComponent(durum.aktif)}/cevap-ac`, { dosya: sonuc.cevap.dosya, klasorde: false })
      .catch(() => {});
  } catch (hata) {
    karsilastirDurumu(cev("Olmadı: {0}", hata.message), true);
  } finally {
    yuvalariCiz();
    await dosyalariYukle();
  }
});

// -- dil değişince ekran seçili dilde yeniden çizilir ----------------------------------------------------
function yenidenCiz() {
  durum.belgeImza = durum.cevapImza = durum.incelemeImza = durum.gidenImza = undefined;
  if (!$("denetle").disabled) $("denetle").textContent = cev("Sızıntı denetimi yap");
  birakAlaniniGuncelle();
  yuvalariCiz();
  seritCiz();
  durumuYenile();
  dosyalariYukle().catch(() => {});
  if ($("yenilikler").open) yenilikleriGoster();
}

// -- başlangıç ---------------------------------------------------------------------------------------
// Doğrudan bağlantı: #belge=belge-2 incelemeyi açar.
const hashBelge = new URLSearchParams(location.hash.slice(1)).get("belge");
if (hashBelge) durum.acikInceleme = hashBelge;

(async () => {
  const yerel = yerelTercih();
  Object.assign(TERCIH, {
    dil: DIL.DILLER.includes(yerel.dil) ? yerel.dil : "tr",
    yazi: ["normal", "buyuk", "cok-buyuk"].includes(yerel.yazi) ? yerel.yazi : "normal",
    karsitlik: yerel.karsitlik === true,
  });
  gorunumUygula();
  await DIL.sec(TERCIH.dil);
  $("denetle").textContent = cev("Sızıntı denetimi yap");
  birakAlaniniGuncelle();
  yuvalariCiz();
  seritCiz();
  durumuYenile();
  dosyalariYukle().catch(() => {});
  seritBaslat();
  setInterval(durumuYenile, 5000);
  setInterval(() => { if (durum.aktif) calismayiYenile().catch(() => {}); }, 4000);
})();
