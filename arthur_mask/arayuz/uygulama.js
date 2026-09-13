"use strict";

const BELIRTEC = document.querySelector('meta[name="am-belirtec"]').content;
const DURUM_ADI = { hazir: "Claude'a hazır", onay_bekliyor: "Onayınızı bekliyor", kirmizi_hat: "Kırmızı hat" };
const BICIM_ADI = { docx: "Word'de aç", udf: "UYAP editöründe aç", txt: "Aç" };
const ETIKET = /\{\{[^{}\s]{1,40}?-\d{1,5}\}\}/g;
const IPUCU = "Word · UDF · PDF · taranmış görüntü · metin — belge bu bilgisayardan çıkmaz";

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

// -- durum, menü ve kurtarma anahtarı -----------------------------------------------------------
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
    $("kurtarma-rozet").hidden = d.kurtarma_saklandi;
    $("guncelleme").hidden = !d.guncelleme;
    if (d.guncelleme) {
      $("guncelleme-metin").textContent = `Arthur Mask ${d.guncelleme.surum} yayımlandı (kurulu: ${d.surum}). Yeni kurulum dosyasını eskisinin üzerine kurun; dosyalarınız korunur.`;
      $("guncelleme-baglanti").href = d.guncelleme.sayfa || d.guncelleme.adres;
    }
    $("kurtarma-saklandi").hidden = !d.kurtarma_saklandi;
  } catch {
    kopru.className = "durum hata";
    kopru.textContent = "Bağlantı yok — Claude Desktop'u açın";
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
    }, d.ad, el("small", {}, `${d.belge_sayisi} belge · ${d.cevap_sayisi} cevap`)),
  )));
  if (!dosyalar.length) {
    $("dosya-listesi").replaceChildren(el("li", { sinif: "not" }, "Henüz dosya yok. İlk belgeyi bırakın."));
  }
  $("yeni-dosya").classList.toggle("aktif", !secili);
  birakAlaniniGuncelle();
  $("calisma").hidden = !secili;
  if (secili) await calismayiYenile();
}

function birakAlaniniGuncelle() {
  const yeni = !durum.aktif;
  $("birak-baslik").textContent = yeni ? "Yeni dosya: ilk belgeyi buraya bırakın" : "Belgeyi buraya bırakın";
  if (!birak.classList.contains("isleniyor")) {
    $("birak-ipucu").textContent = yeni ? `Dosya adı belgeden alınır · ${IPUCU}` : IPUCU;
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
  return ad.replace(/\.[^.]+$/, "").replace(/_+/g, " ").replace(/\s+/g, " ").trim().slice(0, 80) || "Adsız dosya";
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
  birak.classList.add("isleniyor");
  const ipucu = $("birak-ipucu");
  let hataVar = false;
  try {
    if (!durum.aktif) {
      const { klasor } = await api("POST", "/api/dosyalar", { ad: belgedenDosyaAdi(dosyalar[0].name), benzersiz: true });
      durum.yeniDosya = false;
      durum.aktif = klasor;
      durum.belgeImza = durum.cevapImza = durum.incelemeImza = durum.gidenImza = undefined;
    }
    for (const dosya of dosyalar) {
      ipucu.textContent = `${dosya.name} maskeleniyor…`;
      const sonuc = await api("POST", `/api/dosyalar/${encodeURIComponent(durum.aktif)}/belgeler`,
        await dosya.arrayBuffer(), { "X-Dosya-Adi": encodeURIComponent(dosya.name) });
      if (sonuc.durum !== "hazir") { durum.acikInceleme = sonuc.id; durum.kaydir = true; }
    }
  } catch (hata) {
    hataVar = true;
    ipucu.textContent = `Olmadı: ${hata.message}`;
  } finally {
    birak.classList.remove("isleniyor");
    await dosyalariYukle();
    if (hataVar) birak.classList.add("hatali"); else birak.classList.remove("hatali");
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
function cevaplariCiz() {
  const liste = $("cevap-listesi");
  if (!durum.cevaplar.length) {
    liste.replaceChildren(el("li", { sinif: "not" }, "Claude bir taslak teslim ettiğinde ya da belgeyi revize ettiğinde burada gerçek adlarla görünür."));
    return;
  }
  liste.replaceChildren(...durum.cevaplar.map(cevapKarti));
}

function cevapKarti(c) {
  const revizyon = c.tur === "revizyon";
  const metinKutusu = el("div", { sinif: "metin onizleme", tabindex: "0" });
  const sekmeler = el("div", { sinif: "sekmeler", role: "tablist", "aria-label": "Görünüm" });
  const secenekler = [["acik", "Gerçek adlarla"], ["maskeli", "Claude'daki hâli"]];
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
    esitNot.textContent = c.cozulen ? "" : "Bu metinde etiket yok; iki görünüm aynıdır.";
  }
  sekmeCiz();

  const meta = [`${tarih(c.olusturma)} · ${c.bicim.toUpperCase()}`];
  if (revizyon) {
    meta.push(`${c.uygulanan} değişiklik ${c.izli ? "izli olarak " : ""}işlendi`);
    if (c.sorunlar && c.sorunlar.length) meta.push(`${c.sorunlar.length} değişiklik uygulanamadı`);
  }
  meta.push(`${c.cozulen} etiket çözüldü`);

  const uyarilar = [];
  if (c.bilinmeyen.length) uyarilar.push(el("p", { sinif: "uyari" }, `⚠ Kasada olmayan etiket: ${c.bilinmeyen.join(", ")}`));
  if (revizyon && c.sorunlar && c.sorunlar.length) {
    uyarilar.push(el("details", { sinif: "sorunlar" }, el("summary", {}, "Uygulanamayan değişiklikler"),
      el("ul", {}, c.sorunlar.map((s) => el("li", {}, `${s.sira}. ${s.neden}`)))));
  }
  const acDugmesi = revizyon && c.izli ? "Word'de aç (izli değişiklikler)" : (BICIM_ADI[c.bicim] || "Aç");
  return el("li", { sinif: "cevap" },
    el("span", { sinif: "ad" }, c.baslik, " ", revizyon ? el("span", { sinif: "cip hazir" }, "Revizyon") : null),
    el("span", { sinif: "meta" }, meta.join(" · ")),
    el("span", { sinif: "eylemler" },
      el("button", { type: "button", onclick: () => cevapAc(c, false) }, acDugmesi),
      el("button", { type: "button", sinif: "ikincil", onclick: () => cevapAc(c, true) }, "Klasörde göster")),
    el("div", { sinif: "cevap-alt" }, ...uyarilar, sekmeler, metinKutusu),
  );
}

async function cevapAc(cevap, klasorde) {
  await api("POST", `/api/dosyalar/${encodeURIComponent(durum.aktif)}/cevap-ac`, { dosya: cevap.dosya, klasorde });
}

// -- Claude'a giden ve sızıntı denetimi ----------------------------------------------------------
const ARAC_ADI = {
  mcp_belgeler: "Belge listesi", mcp_belge_getir: "Belge metni", mcp_revize: "Revizyon sonucu", mcp_teslim: "Teslim sonucu",
};

function gidenleriCiz() {
  const g = durum.gidenler;
  const ozet = $("giden-ozet");
  if (!g || !g.toplam_yanit) {
    ozet.textContent = "Claude bu dosyadan henüz bir şey almadı. Aldığında, gönderilen her yanıtın maskeli hâli burada listelenir.";
    $("giden-listesi").replaceChildren();
    return;
  }
  ozet.textContent = `Claude'a ${g.toplam_yanit} yanıt gönderildi. ` + (g.toplam_yakalanan
    ? `Çıkış kapısı ${g.toplam_yakalanan} açık değeri göndermeden önce etiketledi.`
    : "Çıkış kapısında yakalanan açık değer olmadı.");
  $("giden-listesi").replaceChildren(...g.kayitlar.map((k) => {
    const detay = el("details", { sinif: "giden-kayit" },
      el("summary", {},
        `${ARAC_ADI[k.arac] || k.arac} · ${tarih(k.zaman)} `,
        k.yakalanan ? el("span", { sinif: "cip onay_bekliyor" }, `kapıda ${k.yakalanan} değer etiketlendi`) : null));
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
  dugme.textContent = "Denetleniyor…";
  try {
    const r = await api("POST", `/api/dosyalar/${encodeURIComponent(durum.aktif)}/denetim`);
    kutu.hidden = false;
    if (r.temiz) {
      kutu.className = "denetim temiz";
      kutu.replaceChildren(
        el("strong", {}, "✓ Temiz"),
        el("p", {}, `${r.taranan_kaynak} metin, kasadaki ${r.kasadaki_deger} gerçek değerin her birine karşı tarandı; hiçbiri bulunmadı.`),
        r.gunluk_var ? null : el("p", { sinif: "not" }, "Bu dosyada Claude'a giden yanıt kaydı yok; kayıt bu sürümle başladı."));
    } else {
      kutu.className = "denetim bulgu";
      kutu.replaceChildren(
        el("strong", {}, "⚠ Açık değer bulundu"),
        el("p", {}, "Aşağıdaki metinlerde kasadaki gerçek değerler etiketsiz geçiyor. ",
          "\"Claude'un yazdığı metin\": Claude bu değeri bir yerden açık görmüş (sohbete yazılan ya da eklenen belge, ya da eski sürümde kaçan bir geçiş). ",
          "\"Çıkış kapısından önce\": değer depodaki maskeli metinde duruyor, Claude'a gönderilirken etiketlenir."),
        el("ul", { sinif: "bulgu-listesi" }, r.bulgular.map((b) => el("li", {},
          el("strong", {}, b.kaynak),
          el("ul", {}, b.eslesmeler.map((e) => el("li", {}, el("mark", {}, e.deger), ` → ${e.etiket} · ${e.adet} kez`)))))));
    }
  } catch (h) {
    kutu.hidden = false;
    kutu.className = "denetim bulgu";
    kutu.textContent = `Denetim yapılamadı: ${h.message}`;
  } finally {
    dugme.disabled = false;
    dugme.textContent = "Sızıntı denetimi yap";
  }
});

// -- başlangıç ---------------------------------------------------------------------------------------
// Doğrudan bağlantı: #belge=belge-2 incelemeyi açar.
const hashBelge = new URLSearchParams(location.hash.slice(1)).get("belge");
if (hashBelge) durum.acikInceleme = hashBelge;

durumuYenile();
dosyalariYukle().catch(() => {});
setInterval(durumuYenile, 5000);
setInterval(() => { if (durum.aktif) calismayiYenile().catch(() => {}); }, 4000);
