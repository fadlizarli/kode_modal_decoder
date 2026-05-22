#!/usr/bin/env python3
"""
Kode Modal Decoder - Chipper ABCDEFGHIY

Penggunaan (menu interaktif):
  python3 main.py

Penggunaan (langsung via flag):
  python3 main.py --fill                 # isi modal dari kode_modal
  python3 main.py --fill --dry-run
  python3 main.py --fill --product "Nama"
  python3 main.py --fill --id 42 55 78
  python3 main.py --check                # cek produk harga belum diisi
  python3 main.py --from-csv file.csv    # update harga dari CSV
  python3 main.py --from-csv file.csv --dry-run
  python3 main.py --export               # export produk ke CSV
  python3 main.py --stats                # statistik produk
  python3 main.py --dupes                # cek produk duplikat/sangat mirip
  python3 main.py --dupes --threshold 0.85
"""

import re
import sys
import csv
import difflib
import argparse
import configparser
import xmlrpc.client
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from collections import defaultdict
from decoder import decode, is_abcdefghiy

LOGS_DIR = Path('logs')

# ─── Config & Koneksi ───────────────────────────────────────────────────────


def load_config(path='config.ini'):
    config = configparser.ConfigParser()
    if not config.read(path):
        print(f"[ERROR] File config tidak ditemukan: {path}")
        print("        Buat dari template: cp config.ini.example config.ini")
        sys.exit(1)
    required = ('url', 'db', 'username', 'password')
    for key in required:
        if not config.get('odoo', key, fallback='').strip():
            print(f"[ERROR] config.ini: key '{key}' di section [odoo] tidak boleh kosong")
            sys.exit(1)
    return config['odoo']


def connect_odoo(url, db, username, password):
    try:
        common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common', allow_none=True)
        uid = common.authenticate(db, username, password, {})
    except Exception as e:
        print(f"[ERROR] Gagal terhubung ke Odoo: {e}")
        sys.exit(1)
    if not uid:
        print("[ERROR] Autentikasi Odoo gagal. Periksa username/password/database.")
        sys.exit(1)
    models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object', allow_none=True)
    return uid, models

# ─── Fetch helpers ──────────────────────────────────────────────────────────


def fetch_candidates(models, db, uid, password, name_filter=None, id_filter=None):
    """Produk: kode_modal terisi, standard_price = 0."""
    domain = [
        ['kode_modal', '!=', False],
        ['kode_modal', '!=', ''],
        ['standard_price', '=', 0],
    ]
    if id_filter:
        domain.append(['id', 'in', id_filter])
    if name_filter:
        domain.append(['name', 'ilike', name_filter])
    return models.execute_kw(
        db, uid, password, 'product.template', 'search_read', [domain],
        {'fields': ['id', 'name', 'kode_modal', 'standard_price', 'product_variant_ids'],
         'order': 'name asc'},
    )


def fetch_empty_prices(models, db, uid, password, name_filter=None, id_filter=None):
    """Produk: harga modal ATAU harga jual = 0 atau 1."""
    domain = [
        '|',
        '|', ['standard_price', '=', 0], ['standard_price', '=', 1],
        '|', ['list_price', '=', 0], ['list_price', '=', 1],
    ]
    if id_filter:
        domain.append(['id', 'in', id_filter])
    if name_filter:
        domain.append(['name', 'ilike', name_filter])
    return models.execute_kw(
        db, uid, password, 'product.template', 'search_read', [domain],
        {'fields': ['id', 'name', 'kode_modal', 'standard_price', 'list_price'],
         'order': 'name asc'},
    )


def fetch_products_by_ids(models, db, uid, password, ids: list[int]):
    return models.execute_kw(
        db, uid, password, 'product.template', 'search_read',
        [[['id', 'in', ids]]],
        {'fields': ['id', 'name', 'product_variant_ids']},
    )


def fetch_all_products(models, db, uid, password, name_filter=None):
    """Semua produk aktif untuk export."""
    domain = []
    if name_filter:
        domain.append(['name', 'ilike', name_filter])
    return models.execute_kw(
        db, uid, password, 'product.template', 'search_read', [domain],
        {'fields': ['id', 'name', 'categ_id', 'kode_modal', 'standard_price', 'list_price'],
         'order': 'name asc'},
    )


def fetch_stats(models, db, uid, password) -> dict:
    """Ambil ringkasan jumlah produk dari Odoo."""
    def count(domain):
        return models.execute_kw(
            db, uid, password, 'product.template', 'search_count', [domain])
    return {
        'total': count([]),
        'with_kode': count([['kode_modal', '!=', False], ['kode_modal', '!=', '']]),
        'eligible_fill': count([
            ['kode_modal', '!=', False], ['kode_modal', '!=', ''],
            ['standard_price', '=', 0],
        ]),
        'harga_belum_lengkap': count([
            '|',
            '|', ['standard_price', '=', 0], ['standard_price', '=', 1],
            '|', ['list_price', '=', 0], ['list_price', '=', 1],
        ]),
    }

# ─── Duplikat helpers ───────────────────────────────────────────────────────


def _normalize_name(name: str) -> str:
    return re.sub(r'\s+', ' ', name.strip().lower())


def find_duplicates(products: list[dict], threshold: float = 0.82):
    """
    Kelompokkan duplikat persis dan temukan pasang sangat mirip.

    Returns:
      exact_groups  — list of list[dict], tiap grup nama yang sama persis (>1 produk)
      similar_pairs — list of (p1, p2, score), pasang dengan ratio >= threshold
    """
    groups: dict[str, list] = defaultdict(list)
    for p in products:
        groups[_normalize_name(p['name'])].append(p)

    exact_groups = [v for v in groups.values() if len(v) > 1]
    exact_keys   = {_normalize_name(p['name']) for g in exact_groups for p in g}

    # Produk unik (tidak masuk duplikat persis)
    unique = {key: group[0] for key, group in groups.items()
              if len(group) == 1 and key not in exact_keys}

    # Pre-filter via word-bucket: hanya bandingkan pasang yang berbagi kata (≥3 huruf)
    word_buckets: dict[str, set] = defaultdict(set)
    for key in unique:
        for word in key.split():
            if len(word) >= 3:
                word_buckets[word].add(key)

    candidate_pairs: set[tuple] = set()
    for keys in word_buckets.values():
        keys_list = sorted(keys)
        for i in range(len(keys_list)):
            for j in range(i + 1, len(keys_list)):
                candidate_pairs.add((keys_list[i], keys_list[j]))

    similar_pairs = []
    for a, b in candidate_pairs:
        ratio = difflib.SequenceMatcher(None, a, b).ratio()
        if ratio >= threshold:
            similar_pairs.append((unique[a], unique[b], ratio))

    similar_pairs.sort(key=lambda x: x[2], reverse=True)
    return exact_groups, similar_pairs


# ─── CSV helpers ────────────────────────────────────────────────────────────


def write_csv(rows: list[dict], run_at: datetime, suffix='') -> Path:
    LOGS_DIR.mkdir(exist_ok=True)
    tag = f'_{suffix}' if suffix else ''
    filename = LOGS_DIR / f"{run_at.strftime('%Y%m%d_%H%M%S')}{tag}.csv"
    fieldnames = list(rows[0].keys()) if rows else []
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return filename


def read_price_csv(path: str) -> tuple[list[dict], list[str]]:
    """Baca CSV harga. Return (rows_valid, errors)."""
    rows, errors = [], []
    try:
        with open(path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            if 'id_produk' not in (reader.fieldnames or []):
                return [], ["Kolom 'id_produk' tidak ditemukan di CSV."]
            for lineno, row in enumerate(reader, start=2):
                raw_id = row.get('id_produk', '').strip()
                if not raw_id:
                    continue
                try:
                    product_id = int(raw_id)
                except ValueError:
                    errors.append(f"Baris {lineno}: id_produk '{raw_id}' bukan angka — dilewati")
                    continue
                harga_modal = harga_jual = None
                for col in ('harga_modal', 'harga_jual'):
                    val = row.get(col, '').strip()
                    if not val:
                        continue
                    try:
                        parsed = float(val.replace('.', '').replace(',', '.'))
                        if col == 'harga_modal':
                            harga_modal = parsed
                        else:
                            harga_jual = parsed
                    except ValueError:
                        errors.append(f"Baris {lineno}: nilai '{col}' tidak valid — dilewati")
                if harga_modal is None and harga_jual is None:
                    continue
                rows.append({'id_produk': product_id,
                             'harga_modal': harga_modal, 'harga_jual': harga_jual})
    except FileNotFoundError:
        return [], [f"File tidak ditemukan: {path}"]
    except Exception as e:
        return [], [f"Gagal membaca CSV: {e}"]
    return rows, errors

# ─── Display helpers ─────────────────────────────────────────────────────────


def fmt_rp(amount) -> str:
    return 'Rp ' + f'{int(amount):,}'.replace(',', '.')


def print_separator(char='─', width=68):
    print('  ' + char * width)


def _price_status(standard_price, list_price) -> str:
    modal_kosong = standard_price in (0, 1)
    jual_kosong = list_price in (0, 1)
    if modal_kosong and jual_kosong:
        return 'Modal & Jual'
    if modal_kosong:
        return 'Modal'
    return 'Jual'


def _header(title: str, dry_run: bool = False):
    print()
    print('=' * 72)
    label = '  [DRY-RUN]' if dry_run else ''
    print(f'    KODE MODAL DECODER  |  {title}{label}')
    print('=' * 72)

# ─── Commands ────────────────────────────────────────────────────────────────


def cmd_fill(models, db, uid, password, args, run_at):
    filter_info = ''
    if args.product:
        filter_info += f'  nama mengandung "{args.product}"'
    if args.ids:
        filter_info += ('  |' if filter_info else '') + f'  ID: {args.ids}'

    print('\n  Mencari produk dengan kode_modal terisi & modal/cost kosong...')
    if filter_info:
        print(f'  Filter:{filter_info}')
    try:
        candidates = fetch_candidates(models, db, uid, password,
                                      name_filter=args.product, id_filter=args.ids)
    except Exception as e:
        print(f'\n[ERROR] Gagal mengambil data: {e}')
        return

    if not candidates:
        print('\n  Tidak ada produk yang perlu diperbarui.')
        return

    to_update, log_rows = [], []
    ts = run_at.strftime('%Y-%m-%d %H:%M:%S')

    for p in candidates:
        kode = (p['kode_modal'] or '').strip()
        if not kode:
            continue
        base = {'waktu': ts, 'id_produk': p['id'], 'nama_produk': p['name'],
                'kode_modal': kode, 'modal_lama': 0, 'modal_baru': ''}
        if not is_abcdefghiy(kode):
            log_rows.append({**base, 'status': 'DILEWATI', 'catatan': 'Format huruf tidak dikenali'})
            continue
        cost = decode(kode)
        if cost is None:
            log_rows.append({**base, 'status': 'DILEWATI', 'catatan': 'Format tidak dikenali'})
            continue
        if cost <= 0:
            log_rows.append({**base, 'status': 'DILEWATI', 'catatan': 'Hasil decode = 0'})
            continue
        to_update.append({'id': p['id'], 'name': p['name'], 'kode_modal': kode,
                          'cost': cost, 'variant_ids': p['product_variant_ids']})
        log_rows.append({**base, 'modal_baru': cost, 'status': 'PENDING', 'catatan': ''})

    skipped = [r for r in log_rows if r['status'] == 'DILEWATI']
    if skipped:
        print()
        print_separator()
        print(f'  DILEWATI ({len(skipped)} produk):')
        print_separator()
        print(f"  {'Nama Produk':<36} {'Kode Modal':<14} Alasan")
        print_separator(char='·')
        for r in skipped:
            print(f"  {r['nama_produk'][:36]:<36} {r['kode_modal']:<14} {r['catatan']}")

    if not to_update:
        print('\n  Tidak ada produk yang bisa di-decode dengan chipper ABCDEFGHIY.')
        if log_rows:
            csv_path = write_csv(log_rows, run_at)
            print(f'\n  Log disimpan: {csv_path}')
        return

    print()
    print_separator()
    print(f'  AKAN DIISI ({len(to_update)} produk):')
    print_separator()
    print(f"  {'No':<4} {'Nama Produk':<36} {'Kode Modal':<14} Modal/Cost")
    print_separator(char='·')
    for i, p in enumerate(to_update, 1):
        print(f"  {i:<4} {p['name'][:36]:<36} {p['kode_modal']:<14} {fmt_rp(p['cost'])}")
    print_separator()

    if args.dry_run:
        for r in log_rows:
            if r['status'] == 'PENDING':
                r['status'] = 'DRY-RUN'
        csv_path = write_csv(log_rows, run_at)
        print()
        print('  Mode DRY-RUN: tidak ada perubahan yang ditulis ke Odoo.')
        print(f'  {len(to_update)} produk siap diperbarui jika dijalankan tanpa --dry-run.')
        print(f'\n  Log disimpan: {csv_path}')
        return

    print()
    confirm = input('  Lanjutkan pengisian modal/cost? [y/N]: ').strip().lower()
    if confirm != 'y':
        print('\n  Dibatalkan.')
        return

    print()
    success = failed = 0
    pending = {r['id_produk']: r for r in log_rows if r['status'] == 'PENDING'}
    for p in to_update:
        try:
            models.execute_kw(db, uid, password, 'product.product', 'write',
                               [p['variant_ids'], {'standard_price': float(p['cost'])}])
            varian_info = f" ({len(p['variant_ids'])} varian)" if len(p['variant_ids']) > 1 else ''
            print(f"  [OK]    {p['name']}{varian_info}  →  {fmt_rp(p['cost'])}")
            pending[p['id']]['status'] = 'OK'
            success += 1
        except Exception as e:
            print(f"  [GAGAL] {p['name']}  →  {e}")
            pending[p['id']]['status'] = 'GAGAL'
            pending[p['id']]['catatan'] = str(e)
            failed += 1

    csv_path = write_csv(log_rows, run_at)
    print()
    print_separator(char='=', width=70)
    print(f'  Selesai: {success} berhasil' + (f', {failed} gagal' if failed else ''))
    print(f'  Log disimpan: {csv_path}')


def cmd_check(models, db, uid, password, args, run_at):
    filter_info = ''
    if args.product:
        filter_info += f'  nama mengandung "{args.product}"'
    if args.ids:
        filter_info += ('  |' if filter_info else '') + f'  ID: {args.ids}'

    print('\n  Mencari produk dengan harga modal atau harga jual belum diisi...')
    if filter_info:
        print(f'  Filter:{filter_info}')
    try:
        products = fetch_empty_prices(models, db, uid, password,
                                      name_filter=args.product, id_filter=args.ids)
    except Exception as e:
        print(f'\n[ERROR] Gagal mengambil data: {e}')
        return

    if not products:
        print('\n  Semua produk sudah memiliki harga modal dan harga jual.')
        return

    ts = run_at.strftime('%Y-%m-%d %H:%M:%S')
    print()
    print_separator()
    print(f'  HARGA BELUM DIISI ({len(products)} produk):')
    print_separator()
    print(f"  {'No':<4} {'ID':<6} {'Nama Produk':<32} {'Kode Modal':<14} {'Modal':<12} {'Jual':<12} Belum Diisi")
    print_separator(char='·')

    rows = []
    for i, p in enumerate(products, 1):
        kode = p['kode_modal'] or '-'
        status = _price_status(p['standard_price'], p['list_price'])
        print(f"  {i:<4} {p['id']:<6} {p['name'][:32]:<32} {kode:<14} "
              f"{fmt_rp(p['standard_price']):<12} {fmt_rp(p['list_price']):<12} {status}")
        rows.append({'waktu': ts, 'id_produk': p['id'], 'nama_produk': p['name'],
                     'kode_modal': kode, 'harga_modal': p['standard_price'],
                     'harga_jual': p['list_price'], 'belum_diisi': status})

    print_separator()
    csv_path = write_csv(rows, run_at, suffix='check')
    print(f'\n  Log disimpan: {csv_path}')


def cmd_from_csv(models, db, uid, password, args, run_at):
    csv_path = args.from_csv
    print(f'\n  Membaca file: {csv_path}')
    rows, errors = read_price_csv(csv_path)

    if errors:
        print()
        for e in errors:
            print(f'  [PERINGATAN] {e}')

    if not rows:
        print('\n  Tidak ada baris valid di CSV.')
        return

    ids = [r['id_produk'] for r in rows]
    try:
        products = fetch_products_by_ids(models, db, uid, password, ids)
    except Exception as e:
        print(f'\n[ERROR] Gagal mengambil data dari Odoo: {e}')
        return

    product_map = {p['id']: p for p in products}
    ts = run_at.strftime('%Y-%m-%d %H:%M:%S')
    to_update, skipped = [], []

    for r in rows:
        pid = r['id_produk']
        if pid not in product_map:
            skipped.append((pid, f'ID {pid} tidak ditemukan di Odoo'))
            continue
        p = product_map[pid]
        to_update.append({'id': pid, 'name': p['name'],
                          'variant_ids': p['product_variant_ids'],
                          'harga_modal': r['harga_modal'], 'harga_jual': r['harga_jual']})

    if skipped:
        print()
        print_separator()
        print(f'  DILEWATI ({len(skipped)} baris):')
        print_separator(char='·')
        for pid, reason in skipped:
            print(f'  ID {pid:<6} — {reason}')

    if not to_update:
        print('\n  Tidak ada produk yang bisa diperbarui.')
        return

    print()
    print_separator()
    print(f'  AKAN DIPERBARUI ({len(to_update)} produk):')
    print_separator()
    print(f"  {'No':<4} {'ID':<6} {'Nama Produk':<34} {'Harga Modal':<16} Harga Jual")
    print_separator(char='·')
    for i, p in enumerate(to_update, 1):
        modal_str = fmt_rp(p['harga_modal']) if p['harga_modal'] is not None else '(tidak diubah)'
        jual_str  = fmt_rp(p['harga_jual'])  if p['harga_jual']  is not None else '(tidak diubah)'
        print(f"  {i:<4} {p['id']:<6} {p['name'][:34]:<34} {modal_str:<16} {jual_str}")
    print_separator()

    log_rows = []

    if args.dry_run:
        for p in to_update:
            log_rows.append({'waktu': ts, 'id_produk': p['id'], 'nama_produk': p['name'],
                             'harga_modal_baru': p['harga_modal'] if p['harga_modal'] is not None else '',
                             'harga_jual_baru': p['harga_jual'] if p['harga_jual'] is not None else '',
                             'status': 'DRY-RUN', 'catatan': ''})
        log_path = write_csv(log_rows, run_at, suffix='import')
        print()
        print('  Mode DRY-RUN: tidak ada perubahan yang ditulis ke Odoo.')
        print(f'\n  Log disimpan: {log_path}')
        return

    print()
    confirm = input('  Lanjutkan update harga? [y/N]: ').strip().lower()
    if confirm != 'y':
        print('\n  Dibatalkan.')
        return

    print()
    success = failed = 0
    for p in to_update:
        status, catatan = 'OK', ''
        try:
            if p['harga_modal'] is not None:
                models.execute_kw(db, uid, password, 'product.product', 'write',
                                  [p['variant_ids'], {'standard_price': p['harga_modal']}])
            if p['harga_jual'] is not None:
                models.execute_kw(db, uid, password, 'product.template', 'write',
                                  [[p['id']], {'list_price': p['harga_jual']}])
            modal_str = fmt_rp(p['harga_modal']) if p['harga_modal'] is not None else '-'
            jual_str  = fmt_rp(p['harga_jual'])  if p['harga_jual']  is not None else '-'
            varian_info = f" ({len(p['variant_ids'])} varian)" if len(p['variant_ids']) > 1 else ''
            print(f"  [OK]    {p['name']}{varian_info}  modal={modal_str}  jual={jual_str}")
            success += 1
        except Exception as e:
            print(f"  [GAGAL] {p['name']}  →  {e}")
            status, catatan = 'GAGAL', str(e)
            failed += 1

        log_rows.append({'waktu': ts, 'id_produk': p['id'], 'nama_produk': p['name'],
                         'harga_modal_baru': p['harga_modal'] if p['harga_modal'] is not None else '',
                         'harga_jual_baru': p['harga_jual'] if p['harga_jual'] is not None else '',
                         'status': status, 'catatan': catatan})

    log_path = write_csv(log_rows, run_at, suffix='import')
    print()
    print_separator(char='=', width=70)
    print(f'  Selesai: {success} berhasil' + (f', {failed} gagal' if failed else ''))
    print(f'  Log disimpan: {log_path}')


def cmd_export(models, db, uid, password, args, run_at):
    name_filter = getattr(args, 'product', None)
    empty_only  = getattr(args, 'empty_only', False)

    if empty_only:
        print('\n  Mengambil produk dengan harga belum diisi...')
        try:
            products = fetch_empty_prices(models, db, uid, password, name_filter=name_filter)
        except Exception as e:
            print(f'\n[ERROR] {e}')
            return
    else:
        info = f'  Filter nama: "{name_filter}"' if name_filter else '  Semua produk'
        print(f'\n  Mengambil produk... ({info.strip()})')
        try:
            products = fetch_all_products(models, db, uid, password, name_filter=name_filter)
        except Exception as e:
            print(f'\n[ERROR] {e}')
            return

    if not products:
        print('\n  Tidak ada produk ditemukan.')
        return

    ts = run_at.strftime('%Y-%m-%d %H:%M:%S')
    rows = []
    for p in products:
        categ = p['categ_id'][1] if p.get('categ_id') else '-'
        rows.append({
            'id_produk':   p['id'],
            'nama_produk': p['name'],
            'kategori':    categ,
            'kode_modal':  p.get('kode_modal') or '',
            'harga_modal': p.get('standard_price', 0),
            'harga_jual':  p.get('list_price', 0),
        })

    csv_path = write_csv(rows, run_at, suffix='export')

    print()
    print_separator()
    print(f'  EXPORT PRODUK ({len(rows)} produk):')
    print_separator()
    print(f"  {'No':<4} {'ID':<6} {'Nama Produk':<34} {'Modal':<14} Jual")
    print_separator(char='·')
    for i, r in enumerate(rows[:10], 1):
        print(f"  {i:<4} {r['id_produk']:<6} {r['nama_produk'][:34]:<34} "
              f"{fmt_rp(r['harga_modal']):<14} {fmt_rp(r['harga_jual'])}")
    if len(rows) > 10:
        print(f"  ... dan {len(rows) - 10} produk lainnya")
    print_separator()
    print(f'\n  File disimpan: {csv_path}')


def cmd_stats(models, db, uid, password, run_at):
    print('\n  Mengambil statistik...')
    try:
        s = fetch_stats(models, db, uid, password)
    except Exception as e:
        print(f'\n[ERROR] {e}')
        return

    print()
    print_separator()
    print('  STATISTIK PRODUK')
    print_separator()
    print(f"  {'Total produk aktif':<40}: {s['total']:>6}")
    print(f"  {'Memiliki kode_modal':<40}: {s['with_kode']:>6}")
    print_separator(char='·')
    print(f"  {'Eligible fill (kode_modal + modal=0)':<40}: {s['eligible_fill']:>6}")
    print(f"  {'Harga belum lengkap (modal/jual 0 atau 1)':<40}: {s['harga_belum_lengkap']:>6}")
    print_separator()

def cmd_dupes(models, db, uid, password, args, run_at):
    threshold   = getattr(args, 'threshold', 0.82)
    name_filter = getattr(args, 'product', None)

    filter_info = f'  Filter nama: "{name_filter}"' if name_filter else '  Semua produk'
    print(f'\n  Mengambil produk... ({filter_info.strip()})')
    try:
        products = fetch_all_products(models, db, uid, password, name_filter=name_filter)
    except Exception as e:
        print(f'\n[ERROR] {e}')
        return

    if not products:
        print('\n  Tidak ada produk ditemukan.')
        return

    print(f'  {len(products)} produk dimuat. Menganalisis duplikat...')
    exact_groups, similar_pairs = find_duplicates(products, threshold=threshold)

    if not exact_groups and not similar_pairs:
        print('\n  Tidak ada duplikat atau produk sangat mirip ditemukan.')
        return

    ts       = run_at.strftime('%Y-%m-%d %H:%M:%S')
    log_rows = []
    grup_num = 0

    if exact_groups:
        print()
        print_separator()
        total_exact = sum(len(g) for g in exact_groups)
        print(f'  DUPLIKAT PERSIS ({len(exact_groups)} grup, {total_exact} produk):')
        print_separator()
        for group in exact_groups:
            grup_num += 1
            print(f'\n  Grup {grup_num}: "{group[0]["name"]}" ({len(group)} produk)')
            print(f"  {'ID':<6} {'Kode Modal':<16} {'Modal':<13} Jual")
            print_separator(char='·')
            for p in group:
                kode = p.get('kode_modal') or '-'
                print(f"  {p['id']:<6} {kode:<16} {fmt_rp(p['standard_price']):<13} {fmt_rp(p['list_price'])}")
                log_rows.append({
                    'tipe': 'Duplikat Persis', 'grup': grup_num,
                    'id_produk': p['id'], 'nama_produk': p['name'],
                    'kode_modal': kode, 'harga_modal': p['standard_price'],
                    'harga_jual': p['list_price'], 'skor_kemiripan': '1.00',
                })
        print_separator()

    if similar_pairs:
        print()
        print_separator()
        print(f'  SANGAT MIRIP ({len(similar_pairs)} pasang, threshold={threshold:.0%}):')
        print_separator()
        print(f"  {'No':<4} {'Skor':<6} {'ID1':<6} {'Nama 1':<30} {'ID2':<6} Nama 2")
        print_separator(char='·')
        for i, (p1, p2, score) in enumerate(similar_pairs, 1):
            grup_num += 1
            print(f"  {i:<4} {score:.2f}  {p1['id']:<6} {p1['name'][:30]:<30} {p2['id']:<6} {p2['name'][:30]}")
            for p in (p1, p2):
                kode = p.get('kode_modal') or '-'
                log_rows.append({
                    'tipe': 'Sangat Mirip', 'grup': grup_num,
                    'id_produk': p['id'], 'nama_produk': p['name'],
                    'kode_modal': kode, 'harga_modal': p['standard_price'],
                    'harga_jual': p['list_price'], 'skor_kemiripan': f'{score:.2f}',
                })
        print_separator()

    if log_rows:
        csv_path = write_csv(log_rows, run_at, suffix='dupes')
        print(f'\n  Log disimpan: {csv_path}')


# ─── Menu interaktif ─────────────────────────────────────────────────────────


def _ask(prompt: str, default: str = '') -> str:
    try:
        val = input(f'  {prompt}').strip()
        return val if val else default
    except (EOFError, KeyboardInterrupt):
        raise KeyboardInterrupt


def _ask_filter() -> tuple[str | None, list[int] | None]:
    """Tanya filter produk secara interaktif. Return (name_filter, id_filter)."""
    print()
    print('  Filter produk:')
    print('  [1] Semua produk')
    print('  [2] Filter by nama')
    print('  [3] Filter by ID')
    choice = _ask('Pilihan [1-3, default=1]: ', '1')

    if choice == '2':
        nama = _ask('Nama produk (substring): ')
        return (nama or None), None
    if choice == '3':
        raw = _ask('ID produk (pisah spasi): ')
        try:
            ids = [int(x) for x in raw.split() if x]
            return None, ids if ids else None
        except ValueError:
            print('  Input ID tidak valid, lanjut tanpa filter.')
    return None, None


def _ask_dryrun() -> bool:
    ans = _ask('Dry-run saja? [y/N]: ', 'n')
    return ans.lower() == 'y'


def show_menu(models, db, uid, password, url, db_name, username):
    run_at = datetime.now()
    while True:
        run_at = datetime.now()
        print()
        print('=' * 72)
        print('    KODE MODAL DECODER  |  Chipper ABCDEFGHIY')
        print('=' * 72)
        print(f'  Odoo : {url}  |  DB : {db_name}  |  User : {username}')
        print_separator()
        print('  [1] Isi modal dari kode_modal (ABCDEFGHIY)')
        print('  [2] Cek produk harga belum diisi')
        print('  [3] Import harga dari CSV')
        print('  [4] Export produk ke CSV')
        print('  [5] Statistik produk')
        print('  [6] Cek produk duplikat / sangat mirip')
        print('  [0] Keluar')
        print_separator()

        try:
            choice = _ask('Pilihan: ')
        except KeyboardInterrupt:
            print('\n\n  Keluar.')
            break

        if choice == '0':
            print('\n  Keluar.')
            break

        elif choice == '1':
            _header('Isi Modal dari Kode Modal')
            name_filter, id_filter = _ask_filter()
            dry_run = _ask_dryrun()
            args = SimpleNamespace(dry_run=dry_run, product=name_filter, ids=id_filter)
            cmd_fill(models, db, uid, password, args, run_at)

        elif choice == '2':
            _header('Cek Harga Belum Diisi')
            name_filter, id_filter = _ask_filter()
            args = SimpleNamespace(product=name_filter, ids=id_filter)
            cmd_check(models, db, uid, password, args, run_at)

        elif choice == '3':
            _header('Import Harga dari CSV')
            csv_file = _ask('Path file CSV: ')
            if not csv_file:
                print('\n  Path tidak boleh kosong.')
            else:
                dry_run = _ask_dryrun()
                args = SimpleNamespace(from_csv=csv_file, dry_run=dry_run)
                cmd_from_csv(models, db, uid, password, args, run_at)

        elif choice == '4':
            _header('Export Produk ke CSV')
            print()
            print('  Export:')
            print('  [1] Semua produk')
            print('  [2] Filter by nama')
            print('  [3] Hanya produk harga belum diisi')
            exp_choice = _ask('Pilihan [1-3, default=1]: ', '1')
            name_filter = None
            empty_only  = False
            if exp_choice == '2':
                name_filter = _ask('Nama produk (substring): ') or None
            elif exp_choice == '3':
                empty_only = True
            args = SimpleNamespace(product=name_filter, empty_only=empty_only)
            cmd_export(models, db, uid, password, args, run_at)

        elif choice == '5':
            _header('Statistik Produk')
            cmd_stats(models, db, uid, password, run_at)

        elif choice == '6':
            _header('Cek Produk Duplikat / Sangat Mirip')
            name_filter, _ = _ask_filter()
            raw_thr = _ask('Threshold kemiripan [0.70-1.00, default=0.82]: ', '0.82')
            try:
                threshold = float(raw_thr)
                threshold = max(0.50, min(1.00, threshold))
            except ValueError:
                threshold = 0.82
            args = SimpleNamespace(product=name_filter, threshold=threshold)
            cmd_dupes(models, db, uid, password, args, run_at)

        else:
            print('\n  Pilihan tidak valid.')
            continue

        try:
            input('\n  Tekan Enter untuk kembali ke menu...')
        except (EOFError, KeyboardInterrupt):
            print('\n\n  Keluar.')
            break

# ─── Entry point ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--fill',      action='store_true')
    parser.add_argument('--check',     action='store_true')
    parser.add_argument('--stats',     action='store_true')
    parser.add_argument('--export',    action='store_true')
    parser.add_argument('--dupes',     action='store_true')
    parser.add_argument('--threshold', type=float, default=0.82, metavar='N')
    parser.add_argument('--from-csv',  metavar='FILE')
    parser.add_argument('--dry-run',   action='store_true')
    parser.add_argument('--product',   metavar='NAMA')
    parser.add_argument('--id',        dest='ids', metavar='ID', nargs='+', type=int)
    args = parser.parse_args()
    run_at = datetime.now()

    cfg = load_config()
    url, db, username, password = cfg['url'], cfg['db'], cfg['username'], cfg['password']

    # Tentukan mode: CLI langsung atau menu
    is_direct = any([args.fill, args.check, args.stats, args.export,
                     args.dupes, args.from_csv, args.dry_run, args.product, args.ids])

    if not is_direct:
        # Mode menu — koneksi dulu, baru tampilkan menu
        print()
        print('=' * 72)
        print('    KODE MODAL DECODER  |  Chipper ABCDEFGHIY')
        print('=' * 72)
        print(f'\n  Odoo : {url}')
        print(f'  DB   : {db}')
        print(f'  User : {username}')
        print('\n  Menghubungkan...', end=' ', flush=True)
        uid, models = connect_odoo(url, db, username, password)
        print(f'OK  (uid={uid})')
        show_menu(models, db, uid, password, url, db, username)
        return

    # Mode CLI langsung
    if args.check:
        _header('Cek Harga Belum Diisi')
    elif args.from_csv:
        _header('Import Harga dari CSV', dry_run=args.dry_run)
    elif args.stats:
        _header('Statistik Produk')
    elif args.export:
        _header('Export Produk ke CSV')
    elif args.dupes:
        _header('Cek Produk Duplikat / Sangat Mirip')
    else:
        _header('Chipper ABCDEFGHIY', dry_run=args.dry_run)

    print(f'\n  Odoo : {url}')
    print(f'  DB   : {db}')
    print(f'  User : {username}')
    print('\n  Menghubungkan...', end=' ', flush=True)
    uid, models = connect_odoo(url, db, username, password)
    print(f'OK  (uid={uid})')

    if args.check:
        cmd_check(models, db, uid, password, args, run_at)
    elif args.from_csv:
        cmd_from_csv(models, db, uid, password, args, run_at)
    elif args.stats:
        cmd_stats(models, db, uid, password, run_at)
    elif args.export:
        args.empty_only = False
        cmd_export(models, db, uid, password, args, run_at)
    elif args.dupes:
        cmd_dupes(models, db, uid, password, args, run_at)
    else:
        cmd_fill(models, db, uid, password, args, run_at)

    print()
    print('=' * 72)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n\n  Keluar.')
