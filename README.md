# Kode Modal Decoder

Aplikasi terminal Python untuk mengelola harga produk di Odoo — mengisi `standard_price` dari `kode_modal` (chipper ABCDEFGHIY), mengecek produk yang belum ada harganya, mengupdate harga dari file CSV, mengekspor produk ke CSV, dan melihat statistik produk.

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

### Menu Interaktif

Jalankan tanpa flag untuk membuka menu interaktif:

```bash
python3 main.py
```

```
========================================================================
    KODE MODAL DECODER  |  Menu Utama
========================================================================

  [1] Isi modal dari kode_modal (ABCDEFGHIY)
  [2] Cek produk harga belum diisi
  [3] Import harga dari CSV
  [4] Export produk ke CSV
  [5] Statistik produk
  [0] Keluar

  Pilih:
```

Setiap opsi akan meminta filter nama/ID dan konfirmasi dry-run secara interaktif.

---

### 1. Isi modal/cost dari kode_modal

Mengisi `standard_price` produk yang `kode_modal`-nya sudah terisi tapi harga modal masih 0.

```bash
# Semua produk eligible
python3 main.py --fill

# Preview tanpa menulis ke Odoo
python3 main.py --fill --dry-run

# Filter nama produk (substring, tidak case-sensitive)
python3 main.py --fill --product "Sepatu"
python3 main.py --fill --product "sepatu nike" --dry-run

# Filter by ID produk
python3 main.py --fill --id 42
python3 main.py --fill --id 42 55 78 --dry-run
```

---

### 2. Cek produk dengan harga belum diisi

Menampilkan produk di mana **harga modal** (`standard_price`) atau **harga jual** (`list_price`) bernilai `0` atau `1` (dianggap belum diisi). Tidak ada yang diubah.

Kolom **Belum Diisi** menunjukkan mana yang bermasalah:

| Nilai | Artinya |
|---|---|
| `Modal & Jual` | Keduanya 0 atau 1 |
| `Modal` | Hanya harga modal yang 0 atau 1 |
| `Jual` | Hanya harga jual yang 0 atau 1 |

```bash
# Semua produk
python3 main.py --check

# Dengan filter nama
python3 main.py --check --product "Sepatu"

# Dengan filter ID
python3 main.py --check --id 42 55
```

---

### 3. Update harga dari file CSV

Mengupdate `standard_price` dan/atau `list_price` dari file CSV yang ditulis manual. Kolom harga yang dikosongkan tidak akan disentuh di Odoo.

```bash
# Preview dulu
python3 main.py --from-csv harga.csv --dry-run

# Eksekusi
python3 main.py --from-csv harga.csv
```

**Format CSV** (header wajib, kolom harga opsional):

```csv
id_produk,harga_modal,harga_jual
42,25000,150000
55,,85000
78,12000,
```

| Kolom | Keterangan |
|---|---|
| `id_produk` | ID `product.template` di Odoo (wajib) |
| `harga_modal` | Nilai baru `standard_price` (kosong = tidak diubah) |
| `harga_jual` | Nilai baru `list_price` (kosong = tidak diubah) |

Angka boleh menggunakan titik sebagai pemisah ribuan: `12.000`, `1.500.000`.

**Alur kerja yang disarankan:**

```bash
# 1. Export daftar produk yang belum ada harga
python3 main.py --check

# 2. Edit file logs/YYYYMMDD_HHMMSS_check.csv — isi kolom harga_modal / harga_jual

# 3. Preview hasil sebelum dieksekusi
python3 main.py --from-csv logs/20260521_143022_check.csv --dry-run

# 4. Eksekusi
python3 main.py --from-csv logs/20260521_143022_check.csv
```

---

### 4. Export produk ke CSV

Mengekspor daftar produk ke file CSV. Berguna untuk melihat semua data produk atau menyiapkan file untuk diisi harganya.

```bash
# Export semua produk
python3 main.py --export

# Export hanya produk dengan harga belum diisi
python3 main.py --export empty

# Export dengan filter nama atau ID
python3 main.py --export --product "Sepatu"
python3 main.py --export --id 42 55 78
```

File disimpan ke `logs/YYYYMMDD_HHMMSS_export.csv`.

**Kolom file export:**

| Kolom | Keterangan |
|---|---|
| `id_produk` | ID `product.template` di Odoo |
| `nama_produk` | Nama produk |
| `kategori` | Nama kategori produk |
| `kode_modal` | Kode modal (`-` jika kosong) |
| `harga_modal` | Nilai `standard_price` saat ini |
| `harga_jual` | Nilai `list_price` saat ini |

---

### 5. Statistik produk

Menampilkan ringkasan statistik produk di Odoo.

```bash
python3 main.py --stats
```

```
========================================================================
    KODE MODAL DECODER  |  Statistik Produk
========================================================================

  ──────────────────────────────────────────────────────────────────
  STATISTIK PRODUK
  ──────────────────────────────────────────────────────────────────
  Total produk aktif              :   1.250
  Produk dengan kode_modal        :     980
  Eligible isi modal (modal = 0)  :      45
  Harga belum lengkap (0 atau 1)  :     120
  ──────────────────────────────────────────────────────────────────
```

---

## Contoh Output Terminal

**Mode isi modal/cost (`--fill --dry-run`)**
```
========================================================================
    KODE MODAL DECODER  |  Chipper ABCDEFGHIY  [DRY-RUN]
========================================================================

  Mencari produk dengan kode_modal terisi & modal/cost kosong...

  ────────────────────────────────────────────────────────────────────
  AKAN DIISI (3 produk):
  ────────────────────────────────────────────────────────────────────
  No   Nama Produk                          Kode Modal     Modal/Cost
  ····································································
  1    Sepatu Nike Air Max                  BEY RT         Rp 25.000
  2    Kemeja Flannel Kotak (2 varian)      AEYY RB        Rp 1.500.000
  3    Celana Cargo Panjang                 AB RB          Rp 12.000
  ────────────────────────────────────────────────────────────────────

  Mode DRY-RUN: tidak ada perubahan yang ditulis ke Odoo.

  Log disimpan: logs/20260521_100000.csv
```

**Mode cek harga belum diisi (`--check`)**
```
========================================================================
    KODE MODAL DECODER  |  Cek Harga Belum Diisi
========================================================================

  Mencari produk dengan harga modal atau harga jual belum diisi...

  ──────────────────────────────────────────────────────────────────────────
  HARGA BELUM DIISI (4 produk):
  ──────────────────────────────────────────────────────────────────────────
  No   ID     Nama Produk                     Kode Modal     Modal         Jual         Belum Diisi
  ··································································································
  1    12     Sepatu Nike Air Max             BEY RT         Rp 0          Rp 0         Modal & Jual
  2    33     Kemeja Flannel                  AB RB          Rp 0          Rp 150.000   Modal
  3    55     Celana Cargo                    -              Rp 85.000     Rp 1         Jual
  4    78     Topi Baseball                   GH RB          Rp 1          Rp 1         Modal & Jual
  ──────────────────────────────────────────────────────────────────────────

  Log disimpan: logs/20260521_100000_check.csv
```

**Mode import CSV (`--from-csv`)**
```
========================================================================
    KODE MODAL DECODER  |  Import Harga dari CSV  [DRY-RUN]
========================================================================

  Membaca file: logs/20260521_100000_check.csv

  ────────────────────────────────────────────────────────────────────
  AKAN DIPERBARUI (3 produk):  [DRY-RUN]
  ────────────────────────────────────────────────────────────────────
  No   ID     Nama Produk                       Harga Modal      Harga Jual
  ·········································································
  1    12     Sepatu Nike Air Max               Rp 25.000        Rp 150.000
  2    33     Kemeja Flannel                    Rp 12.000        (tidak diubah)
  3    55     Celana Cargo                      (tidak diubah)   Rp 85.000
  ────────────────────────────────────────────────────────────────────

  Mode DRY-RUN: tidak ada perubahan yang ditulis ke Odoo.

  Log disimpan: logs/20260521_100001_import.csv
```

**Mode export produk (`--export`)**
```
========================================================================
    KODE MODAL DECODER  |  Export Produk ke CSV
========================================================================

  Mengambil semua produk aktif...

  ────────────────────────────────────────────────────────────────────
  PRODUK DIEXPORT (1.250 produk):
  ────────────────────────────────────────────────────────────────────
  No   ID     Nama Produk                     Kategori         Modal         Jual
  ················································································
  1    12     Sepatu Nike Air Max             Sepatu           Rp 0          Rp 0
  2    33     Kemeja Flannel                  Pakaian          Rp 0          Rp 150.000
  ...
  ────────────────────────────────────────────────────────────────────

  File disimpan: logs/20260521_100002_export.csv
```

---

## Log CSV

Setiap run otomatis menyimpan log ke folder `logs/`.

| Nama file | Kapan dibuat |
|---|---|
| `logs/YYYYMMDD_HHMMSS.csv` | Setiap run isi modal/cost dari kode_modal |
| `logs/YYYYMMDD_HHMMSS_check.csv` | Setiap run `--check` |
| `logs/YYYYMMDD_HHMMSS_import.csv` | Setiap run `--from-csv` |
| `logs/YYYYMMDD_HHMMSS_export.csv` | Setiap run `--export` |

**Kolom log isi modal/cost:**

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

**Kolom log cek harga belum diisi:**

| Kolom | Keterangan |
|---|---|
| `waktu` | Timestamp run |
| `id_produk` | ID `product.template` di Odoo |
| `nama_produk` | Nama produk |
| `kode_modal` | Isi kode modal (`-` jika kosong) |
| `harga_modal` | Nilai `standard_price` saat ini |
| `harga_jual` | Nilai `list_price` saat ini |
| `belum_diisi` | `Modal & Jual` / `Modal` / `Jual` |

**Kolom log import CSV:**

| Kolom | Keterangan |
|---|---|
| `waktu` | Timestamp run |
| `id_produk` | ID `product.template` di Odoo |
| `nama_produk` | Nama produk |
| `harga_modal_baru` | Nilai yang ditulis ke `standard_price` (kosong = tidak diubah) |
| `harga_jual_baru` | Nilai yang ditulis ke `list_price` (kosong = tidak diubah) |
| `status` | `OK` / `GAGAL` / `DRY-RUN` |
| `catatan` | Pesan error jika gagal |

**Kolom log export:**

| Kolom | Keterangan |
|---|---|
| `id_produk` | ID `product.template` di Odoo |
| `nama_produk` | Nama produk |
| `kategori` | Nama kategori produk |
| `kode_modal` | Kode modal (`-` jika kosong) |
| `harga_modal` | Nilai `standard_price` saat ini |
| `harga_jual` | Nilai `list_price` saat ini |

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
