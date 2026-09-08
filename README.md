# 🎯 Trench Simulator

**[@trenchsimulator_bot](https://t.me/trenchsimulator_bot)**

Simulator trading memecoin real-time di Telegram — latihan "turun ke trenches" tanpa risiko kehilangan uang asli. Semua transaksi pakai saldo virtual dan data harga live dari Dexscreener.

---

## ✨ Fitur

### Trading Simulasi
- Paste Contract Address (CA) langsung ke chat untuk scan harga & beli
- Buy nominal preset ($10 / $50 / $100 / $500) atau custom
- DCA (buy tambahan di posisi yang sudah terbuka)
- Sell dengan preset persentase custom (default 25% / 50% / 100%, bisa diatur sendiri)
- **Sell Initial** — jual sebagian token senilai modal awal, sisanya jadi profit murni yang bisa dibiarkan jalan
- Portofolio dengan pagination & sort (Recent / by Profit)
- Tombol Refresh untuk narik ulang harga terbaru tanpa reload halaman

### Otomatisasi
- **Auto Take Profit & Stop Loss** — preset persen atau custom, auto-sell saat target tercapai
- **Scanner** — notifikasi otomatis saat ada token baru terdeteksi (polling tiap 30 detik)
- **Alert harga custom** — set target naik/turun untuk token tertentu, dapat notifikasi saat tercapai

### Analitik & Sosial
- `/stats` — total trades, win rate (W/L), rata-rata hold time, biggest win/loss
- `/history` — riwayat transaksi terakhir dengan win rate
- **Leaderboard** — ranking semua user berdasarkan realized PnL
- **Chart snapshot** — grafik perubahan harga 5m/1h/6h/24h per token

### Lainnya
- `/reset` — reset saldo, posisi, dan history ke awal (dengan konfirmasi)

---

## 🤖 Daftar Command

| Command | Fungsi |
|---|---|
| `/start` | Buka menu utama |
| `/pnl` | Cek portofolio & jual/beli |
| `/history` | Riwayat transaksi |
| `/stats` | Statistik trading |
| `/alerts` | Lihat & kelola alert harga aktif |
| `/scanner` | Aktif/nonaktifkan auto scan token baru |
| `/reset` | Reset saldo & data ke awal |

---

## 🛠 Tech Stack

- **Python 3** + [pyTelegramBotAPI](https://github.com/eternnoir/pyTelegramBotAPI) — interaksi bot Telegram
- **Requests** — fetch data harga dari [Dexscreener API](https://docs.dexscreener.com/api/reference)
- **Matplotlib** — generate chart snapshot perubahan harga
- Data user disimpan **in-memory** (dict), reset saat proses restart

---

## 🚀 Setup & Deploy

### 1. Buat bot di Telegram
1. Chat dengan [@BotFather](https://t.me/BotFather)
2. `/newbot` → ikuti instruksinya → salin token yang diberikan

### 2. Konfigurasi environment variable
Bot ini membaca token dari environment variable, **bukan** hardcoded di kode:

```
BOT_TOKEN=isi_dengan_token_dari_botfather
```

Jangan pernah commit token langsung ke kode atau repo publik.

### 3. Deploy ke Railway
1. Push kode ini ke repository (GitHub/GitLab)
2. Buat project baru di [Railway](https://railway.app), hubungkan ke repo tersebut
3. Buka tab **Variables** → tambahkan `BOT_TOKEN` dengan token dari langkah 1
4. Railway otomatis mendeteksi `requirements.txt` dan menjalankan bot

### 4. Jalankan secara lokal (opsional)
```bash
pip install -r requirements.txt
export BOT_TOKEN="isi_dengan_token_dari_botfather"
python bot_fixed.py
```

---

## 📁 Struktur File

```
.
├── bot_fixed.py       # Kode utama bot
├── requirements.txt   # Daftar dependency Python
└── README.md
```

---

## ⚠️ Keterbatasan Saat Ini

- **Data tidak persisten** — saldo, posisi, dan history hilang setiap kali proses bot restart (misalnya redeploy di Railway). Untuk penggunaan jangka panjang, disarankan memindahkan `users_db` ke SQLite atau PostgreSQL.
- **Chart bukan candle historis penuh** — hanya snapshot perubahan harga 5m/1h/6h/24h, karena Dexscreener API gratis tidak menyediakan data OHLC historis.
- **Belum ada rate limiting** per user untuk mencegah spam klik Buy/Sell.
- Harga & data token bergantung sepenuhnya pada ketersediaan [Dexscreener API](https://dexscreener.com).

---

## 📌 Disclaimer

Trench Simulator adalah **simulator edukatif** menggunakan saldo virtual. Tidak ada transaksi crypto asli yang terjadi, dan bot ini tidak memberikan saran finansial. Gunakan untuk latihan strategi, bukan sebagai acuan keputusan investasi nyata.
