"""Kurulum paketi yardımcıları: Claude Desktop kaydı ve güncelleme bildirimi."""

import json
import sys

import pytest

from arthur_mask import claude_ayari, guncelleme

yalniz_windows = pytest.mark.skipif(sys.platform == "darwin", reason="Windows yapılandırma yolları")
UZ = guncelleme.KURULUM_UZANTISI


@yalniz_windows
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
    assert veri["mcpServers"]["arthur-mask"]["args"][-2:] == ["-c", claude_ayari.KOPRU_KOMUTU]
    assert list(klasik.glob("claude_desktop_config.arthur-mask-yedek-*.json"))
    assert "arthur-mask" in json.loads((msix / "claude_desktop_config.json").read_text(encoding="utf-8"))["mcpServers"]

    claude_ayari.sil()
    veri = json.loads((klasik / "claude_desktop_config.json").read_text(encoding="utf-8"))
    assert "arthur-mask" not in veri["mcpServers"] and "baska" in veri["mcpServers"]


@yalniz_windows
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
        {"html_url": "s1", "assets": [{"name": f"ArthurMask-Kurulum-1.0.0.{UZ}", "browser_download_url": "a"}]},
        {"html_url": "s2", "assets": [{"name": f"ArthurMask-Kurulum-1.10.0.{UZ}", "browser_download_url": "b"},
                                      {"name": "baska.zip"}]},
        {"html_url": "s3", "prerelease": True, "assets": [{"name": f"ArthurMask-Kurulum-9.0.0.{UZ}"}]},
    ]
    assert guncelleme.en_yeni(surumler) == {"surum": "1.10.0", "adres": "b", "sayfa": "s2"}
    assert guncelleme.en_yeni([{"assets": []}]) is None
    kalici = [{"name": "Arthur Mask 1.2.3 — Windows kurulum dosyası", "html_url": "s",
               "assets": [{"name": f"ArthurMask-Kurulum.{UZ}", "browser_download_url": "k"}]}]
    assert guncelleme.en_yeni(kalici) == {"surum": "1.2.3", "adres": "k", "sayfa": "s"}
    assert guncelleme.en_yeni([{"name": "başka", "assets": [{"name": f"ArthurMask-Kurulum.{UZ}"}]}]) is None


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS yapılandırma yolu")
def test_macos_claude_desktop_kaydi(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    yol = tmp_path / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    yol.parent.mkdir(parents=True)
    yol.write_text(json.dumps({"mcpServers": {"baska": {"command": "x"}}}), encoding="utf-8")
    assert not claude_ayari.kayitli_mi()
    assert claude_ayari.kaydet() == [yol] and claude_ayari.kayitli_mi()
    girdi = json.loads(yol.read_text(encoding="utf-8"))["mcpServers"]
    assert girdi["baska"] == {"command": "x"}
    assert girdi["arthur-mask"]["args"] == ["-I", "-B", "-c", claude_ayari.KOPRU_KOMUTU]
    claude_ayari.sil()
    assert "arthur-mask" not in json.loads(yol.read_text(encoding="utf-8"))["mcpServers"]


def test_kurulum_dosyasi_yalniz_bu_platformun_uzantisi():
    baska = "dmg" if UZ == "exe" else "exe"
    kalici = [{"name": "Arthur Mask 1.2.3", "html_url": "s",
               "assets": [{"name": f"ArthurMask-Kurulum.{baska}", "browser_download_url": "x"}]}]
    assert guncelleme.en_yeni(kalici) is None
