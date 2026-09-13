"""Kurulum paketi yardımcıları: Claude Desktop kaydı ve güncelleme bildirimi."""

import json

from arthur_mask import claude_ayari, guncelleme


def test_claude_desktop_kaydi_diger_ayarlari_korur_ve_yedekler(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    msix = tmp_path / "Local" / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude"
    klasik = tmp_path / "Roaming" / "Claude"
    msix.mkdir(parents=True)
    klasik.mkdir(parents=True)
    mevcut = {"mcpServers": {"baska": {"command": "x"}}, "preferences": {"tema": "koyu"}}
    (klasik / "claude_desktop_config.json").write_text(json.dumps(mevcut), encoding="utf-8")

    yazilan = claude_ayari.kaydet()
    assert len(yazilan) == 2
    veri = json.loads((klasik / "claude_desktop_config.json").read_text(encoding="utf-8"))
    assert veri["mcpServers"]["baska"] == {"command": "x"} and veri["preferences"] == {"tema": "koyu"}
    assert veri["mcpServers"]["arthur-mask"]["args"] == ["-c", claude_ayari.KOPRU_KOMUTU]
    assert list(klasik.glob("claude_desktop_config.arthur-mask-yedek-*.json"))
    assert "arthur-mask" in json.loads((msix / "claude_desktop_config.json").read_text(encoding="utf-8"))["mcpServers"]

    claude_ayari.sil()
    veri = json.loads((klasik / "claude_desktop_config.json").read_text(encoding="utf-8"))
    assert "arthur-mask" not in veri["mcpServers"] and "baska" in veri["mcpServers"]


def test_bozuk_yapilandirmaya_dokunulmaz(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "yok"))
    yol = tmp_path / "Claude" / "claude_desktop_config.json"
    yol.parent.mkdir()
    yol.write_text("{ bozuk", encoding="utf-8")
    assert claude_ayari.kaydet() == []
    assert yol.read_text(encoding="utf-8") == "{ bozuk"


def test_en_yeni_kurulum_dosyasi_secilir():
    surumler = [
        {"html_url": "s1", "assets": [{"name": "ArthurMask-Kurulum-1.0.0.exe", "browser_download_url": "a"}]},
        {"html_url": "s2", "assets": [{"name": "ArthurMask-Kurulum-1.10.0.exe", "browser_download_url": "b"},
                                      {"name": "baska.zip"}]},
        {"html_url": "s3", "prerelease": True, "assets": [{"name": "ArthurMask-Kurulum-9.0.0.exe"}]},
    ]
    assert guncelleme.en_yeni(surumler) == {"surum": "1.10.0", "adres": "b", "sayfa": "s2"}
    assert guncelleme.en_yeni([{"assets": []}]) is None
