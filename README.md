# AgentDesk — Yerel Yapay Zeka Kodlama Ajanı & Çalışma Alanı Masaüstü Uygulaması

> Kurumsal düzeyde, koyu temalı bir **Otonom Çalışma Alanı Ajanı**. Belirli bir yerel
> dizine bağlanır; dosyaları okur/yazar, terminal komutları çalıştırır, git'i yönetir ve
> kendi çıktısını doğrular — tıpkı GitHub Copilot Workspace / Cursor / Codex CLI gibi,
> ancak **tamamen yerel** bir Ollama sunucusuyla.

![durum](https://img.shields.io/badge/build-GitHub%20Actions-2f81f7)
![lisans](https://img.shields.io/badge/license-MIT-3fb950)
![python](https://img.shields.io/badge/python-3.10+-d29922)

---

## ✨ Özellikler

| Alan | Yetenek |
|------|---------|
| **LLM Arka Ucu** | Ollama — varsayılan `http://localhost:11435`, birincil model `qwen3.5-9b-abliterated` |
| **Ajan Döngüsü** | Araç çağrısı protokolü, canlı akış (streaming), kendi kendini düzeltme, kota denetimi |
| **Dosya Sistemi** | Korumalı (sandbox) oluşturma / okuma / düzenleme / yeniden adlandırma / silme + canlı **diff** |
| **Terminal** | Headless komut yürütme, stdout/stderr/çıkış kodu yakalama, zaman aşımı, tehlike filtresi |
| **Git** | `init`, `add`, `commit`, `branch`, `checkout`, `status`, `diff`, `log` |
| **Kota Motoru** | Günlük istek / token / yürütme / aktif-süre sınırları; şifreli SQLite deposu |
| **Yönetici Aracı** | `UsageLimitEditor.exe` — kotaları düzenler, sıfırlar, kilitler (yönetici kodu ile) |
| **GUI** | PySide6 (Qt) çok bölmeli, koyu temalı, Cursor tarzı masaüstü arayüzü |

---

## Mimarî

```
agentdesk/
├── core/                  # Yapılandırma, Ollama istemcisi, ajan döngüsü, kota motoru
│   ├── config.py          #   AppConfig + JSON kalıcılığı (varsayılan port 11435)
│   ├── ollama_client.py   #   Akış / yeniden deneme / keep-alive / token sayımı
│   ├── agent.py           #   AgentWorker (QThread) — araç döngüsü & sinyaller
│   ├── tool_parser.py     #   Model çıktısından toleranslı araç çağrısı çıkarma
│   ├── tokenizer.py       #   Token tahmini (sunucu yoksa ön kontrol için)
│   ├── limits_store.py    #   Fernet-şifreli kota politikası (SQLite)
│   ├── usage_tracker.py   #   Kullanım sayaçları + canlı kota uygulama
│   ├── session_store.py   #   Sohbet oturumlarının JSON kalıcılığı
│   ├── markdown.py        #   Güvenli Markdown → HTML (sohbet balonları)
│   └── paths.py           #   Platform-bağımsız veri dizinleri
├── tools/                 # Ajanın çalışma alanı yetenekleri
│   ├── workspace.py       #   Sandbox dosya işlemleri + diff üretimi
│   ├── terminal.py        #   Güvenli komut çalıştırıcı (zaman aşımı + tehlike filtresi)
│   ├── git.py             #   Git sarmalayıcı
│   └── registry.py        #   Araç kataloğu & dağıtım (model'e açıklama üretir)
├── ui/                    # PySide6 koyu temalı arayüz
│   ├── main_window.py     #   Sol kenar çubuğu / sohbet / editör / terminal
│   ├── chat_panel.py      #   Markdown balonlar + canlı Yürütme Kartları
│   ├── file_tree.py       #   Çalışma alanı dosya gezgini
│   ├── editor_panel.py    #   Sekmeli kod editörü + renkli diff görüntüleyici
│   ├── terminal_panel.py  #   Gömülü konsol (komut geçmişi ile)
│   ├── usage_panel.py     #   Canlı kota göstergeleri
│   ├── settings_dialog.py #   Ollama/model/GitHub ayarları
│   ├── syntax.py          #   Sözdizimi vurgulama
│   └── theme.py           #   GitHub-dark esinli QSS teması
├── usage_editor/          # Kullanım Sınırı Düzenleyicisi (ayrı .exe)
│   └── main.py
└── app.py                 # Ana uygulama giriş noktası
```

**İletişim protokolü.** `OllamaClient`, `POST /api/chat` üzerinde satır-sonlu-JSON
(NDJSON) akışını işler; `StreamChunk` deltalarını arayüze iletir ve son çerçevedeki
`prompt_eval_count` / `eval_count` değerlerini kota motoruna besler. Bağlantı/zaman
aşımı hataları **üstel geri çekilme + jitter** ile yeniden denenir; HTTP 5xx bilinçli
olarak körü körüne yeniden POST edilmez (üretim yinelemesini önlemek için).

**Araç protokolü.** Modelden her araç çağrısı için şu biçimde bir blok üretmesi istenir:

````
```tool
{"tool": "write_file", "args": {"path": "src/app.py", "content": "..."}}
```
````

`tool_parser` çitli/çitsiz JSON'u, anahtar takma adlarını (`name`/`action`,
`args`/`parameters`…) ve sonda kalan virgülleri toleransla çözümler. Her sonuç modele
`OBSERVATION` olarak geri döner; hata alan ajan kök nedeni okuyup yeniden dener.

---

## Kurulum ve Çalıştırma (Geliştirme)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

# Ana uygulama
python -m agentdesk

# Kota yönetim aracı
python -m agentdesk.usage_editor
```

> **Not — Ollama portu:** Uygulama varsayılan olarak `http://localhost:11435` hedefler.
> Ollama'nızı bu portta başlatın: `OLLAMA_HOST=0.0.0.0:11435 ollama serve`
> (veya Ayarlar panelinden ana bilgisayar/portu değiştirin). Model: `qwen3.5-9b-abliterated`.

---

## Test

```bash
QT_QPA_PLATFORM=offscreen pytest -q
```

Test paketi; yapılandırma, araç ayrıştırıcı, Markdown güvenliği, şifreli kota deposu,
canlı kota uygulaması, sandbox dosya işlemleri, terminal (zaman aşımı + tehlike filtresi),
git, sahte Ollama sunucusuna karşı istemci ve **uçtan uca ajan döngüsü** ile GUI duman
testlerini kapsar.

---

## CI/CD — GitHub Actions

`.github/workflows/build.yml` şu akışı otomatikleştirir:

1. **`test`** — Ubuntu + Windows'da headless (offscreen) test paketi.
2. **`build-windows`** — PyInstaller ile **iki bağımsız yürütülebilir** üretir:
   - `dist/AgentDesk.exe`
   - `dist/UsageLimitEditor.exe`
   Her ikisini de `.zip` olarak iş akışı **yapıtı (artifact)** diye yükler.
3. **`release`** — `v*` etiketi itildiğinde veya elle (`workflow_dispatch`) tetiklendiğinde,
   her iki `.exe`'yi içeren bir **taslak GitHub Sürümü** oluşturur.

**Kullanıcı için:** kodu itin → *Actions* sekmesinden `AgentDesk-windows` /
`UsageLimitEditor-windows` yapıtlarını indirin; ya da `vX.Y.Z` etiketi itip *Releases*
altındaki taslak sürümü yayımlayın.

```bash
git tag v1.0.0 && git push origin v1.0.0   # taslak release üretir
```

---

## Kota ve `UsageLimitEditor`

Kota politikası **Fernet ile şifrelenmiş** olarak paylaşılan SQLite deposunda tutulur;
ana uygulama her faturalandırılabilir eylemden önce bu depoyu **canlı** okur, bu yüzden
düzenleyicide yapılan değişiklik yeniden başlatma gerektirmez.

- Günlük istek / token / yürütme / aktif-süre üst sınırları
- Oturum başına token sınırı
- Geliştirici modu geçersiz kılma
- Yönetici kodu ile kilitleme (varsayılan kod: `admin123` — **ilk iş olarak değiştirin**)

---

## Güvenlik Sınırları

- Tüm dosya eylemleri çalışma alanı köküne **hapsedilmiştir** (`..` ve sembolik kaçışlar reddedilir).
- Açıkça yıkıcı komutlar (`rm -rf /`, `mkfs`, disk biçimlendirme, `shutdown`…) çalıştırılmaz.
- Git kimlik bilgilerine dokunulmaz; uzak işlemleri kullanıcının kendi yapılandırmasına bırakılır.

---

## Lisans

MIT — ayrıntılar için [`LICENSE`](LICENSE).
