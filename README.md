# Kode Modal Decoder

Aplikasi terminal Python untuk mengisi kolom **modal/cost** (`standard_price`) produk di Odoo secara otomatis, berdasarkan `kode_modal` yang sudah terisi menggunakan chipper **ABCDEFGHIY**.

Aplikasi ini hanya memproses produk yang memenuhi dua syarat:
- `kode_modal` **terisi**
- `standard_price` **kosong** (= 0)

---

## Dependensi Odoo

Modul ini bekerja bersama dua modul Odoo:

| Modul | Fungsi |
|---|---|
| [`product_kode_modal`](https://github.com/fadlizarli/product_kode_modal) | Menambahkan field `kode_modal` pada produk |
| [`kode_modal_generator`](https://github.com/fadlizarli/kode_modal_generator) | Generate `kode_modal` dari `standard_price` menggunakan chipper |

---

## Cara Kerja Chipper ABCDEFGHIY

Setiap digit dienkode ke huruf:

| Digit | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 0 |
|---|---|---|---|---|---|---|---|---|---|---|
| Huruf | A | B | C | D | E | F | G | H | I | Y |

Harga juga dikompresi dengan suffix satuan:

| Suffix | Pengali |
|---|---|
| `JT` | × 1.000.000 |
| `RB` | × 1.000 |
| `RT` | × 100 |
| *(tanpa suffix)* | × 1 |

**Contoh decode:**

| `kode_modal` | Proses | `standard_price` |
|---|---|---|
| `AB RB` | 12 × 1.000 | Rp 12.000 |
| `BEY RT` | 250 × 100 | Rp 25.000 |
| `AEYY RB` | 1.500 × 1.000 | Rp 1.500.000 |
| `A JT` | 1 × 1.000.000 | Rp 1.000.000 |

---

## Instalasi

Tidak ada dependensi eksternal. Cukup Python 3.10+.

```bash
git clone https://github.com/fadlizarli/kode_modal_decoder
cd kode_modal_decoder
cp config.ini.example config.ini
```

Edit `config.ini` dengan kredensial Odoo:

```ini
[odoo]
url      = http://localhost:8069
db       = nama_database
username = admin
password = password_anda
```

---

## Penggunaan

### Semua produk eligible
```bash
python3 main.py
```

### Preview tanpa menulis ke Odoo (dry-run)
```bash
python3 main.py --dry-run
```

### Filter nama produk (substring, tidak case-sensitive)
```bash
python3 main.py --product "Sepatu"
python3 main.py --product "sepatu nike" --dry-run
```

### Filter by ID produk
```bash
python3 main.py --id 42
python3 main.py --id 42 55 78 --dry-run
```

---

## Contoh Output Terminal

```
========================================================================
    KODE MODAL DECODER  |  Chipper ABCDEFGHIY  [DRY-RUN]
========================================================================

  Odoo : http://localhost:8069
  DB   : toko_db
  User : admin

  Menghubungkan... OK  (uid=2)

  Mencari produk dengan kode_modal terisi & modal/cost kosong...

  ────────────────────────────────────────────────────────────────────
  AKAN DIISI (3 produk):
  ────────────────────────────────────────────────────────────────────
  No   Nama Produk                          Kode Modal     Modal/Cost
  ····································································
  1    Sepatu Nike Air Max                  BEY RT         Rp 25.000
  2    Kemeja Flannel Kotak                 AEYY RB        Rp 1.500.000
  3    Celana Cargo Panjang                 AB RB          Rp 12.000
  ────────────────────────────────────────────────────────────────────

  Mode DRY-RUN: tidak ada perubahan yang ditulis ke Odoo.
  3 produk siap diperbarui jika dijalankan tanpa --dry-run.

  Log disimpan: logs/20260521_100000.csv
```

---

## Log CSV

Setiap run otomatis menyimpan log ke `logs/YYYYMMDD_HHMMSS.csv`.

Kolom yang tersedia:

| Kolom | Keterangan |
|---|---|
| `waktu` | Timestamp run |
| `id_produk` | ID `product.template` di Odoo |
| `nama_produk` | Nama produk |
| `kode_modal` | Kode yang diproses |
| `modal_lama` | Nilai `standard_price` sebelumnya (selalu 0) |
| `modal_baru` | Hasil decode (kosong jika dilewati) |
| `status` | `OK` / `GAGAL` / `DRY-RUN` / `DILEWATI` |
| `catatan` | Alasan skip atau pesan error |

Folder `logs/` tidak ikut ke repository (sudah masuk `.gitignore`).

---

## Struktur File

```
kode_modal_decoder/
├── main.py               # Aplikasi utama
├── decoder.py            # Logika decode chipper ABCDEFGHIY
├── config.ini.example    # Template konfigurasi
├── config.ini            # Konfigurasi lokal (tidak di-commit)
└── logs/                 # Log CSV per run (tidak di-commit)
```
