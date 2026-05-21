#!/usr/bin/env python3
"""
Kode Modal Decoder - Chipper ABCDEFGHIY
Mengisi kolom modal/cost (standard_price) dari kode_modal yang sudah terisi,
khusus produk yang belum memiliki harga modal (standard_price = 0).

Penggunaan:
  python3 main.py                        # semua produk eligible
  python3 main.py --dry-run             # preview saja, tidak ditulis
  python3 main.py --product "Nama"      # filter nama (substring, case-insensitive)
  python3 main.py --id 42 55 78         # filter by ID produk (bisa lebih dari satu)
  python3 main.py --check               # cek produk dengan harga modal/jual belum diisi
  python3 main.py --check --product "Sepatu"
"""

import sys
import csv
import argparse
import configparser
import xmlrpc.client
from datetime import datetime
from pathlib import Path
from decoder import decode, is_abcdefghiy

LOGS_DIR = Path('logs')


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


def fetch_candidates(models, db, uid, password, name_filter=None, id_filter=None):
    """Ambil produk: kode_modal terisi, standard_price kosong (= 0)."""
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
        db, uid, password,
        'product.template', 'search_read',
        [domain],
        {'fields': ['id', 'name', 'kode_modal', 'standard_price', 'product_variant_ids'], 'order': 'name asc'},
    )


def fetch_empty_prices(models, db, uid, password, name_filter=None, id_filter=None):
    """Ambil produk di mana harga modal ATAU harga jual belum diisi (= 0 atau 1)."""
    domain = [
        '|',
        ['standard_price', 'in', [0, 1]],
        ['list_price', 'in', [0, 1]],
    ]
    if id_filter:
        domain.append(['id', 'in', id_filter])
    if name_filter:
        domain.append(['name', 'ilike', name_filter])
    return models.execute_kw(
        db, uid, password,
        'product.template', 'search_read',
        [domain],
        {'fields': ['id', 'name', 'kode_modal', 'standard_price', 'list_price'], 'order': 'name asc'},
    )


def _price_status(standard_price, list_price) -> str:
    """Tentukan kolom mana yang belum diisi."""
    modal_kosong = standard_price in (0, 1)
    jual_kosong = list_price in (0, 1)
    if modal_kosong and jual_kosong:
        return 'Modal & Jual'
    if modal_kosong:
        return 'Modal'
    return 'Jual'


def write_csv(rows: list[dict], run_at: datetime, suffix='') -> Path:
    """Tulis log rows ke CSV di folder logs/. Return path file."""
    LOGS_DIR.mkdir(exist_ok=True)
    tag = f'_{suffix}' if suffix else ''
    filename = LOGS_DIR / f"{run_at.strftime('%Y%m%d_%H%M%S')}{tag}.csv"
    fieldnames = list(rows[0].keys()) if rows else []
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return filename


def fmt_rp(amount) -> str:
    return 'Rp ' + f'{int(amount):,}'.replace(',', '.')


def print_separator(char='─', width=68):
    print('  ' + char * width)


def cmd_check(models, db, uid, password, args, run_at):
    """Laporan produk dengan harga modal atau harga jual belum diisi (0 atau 1)."""
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
        sys.exit(1)

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
        modal = fmt_rp(p['standard_price'])
        jual = fmt_rp(p['list_price'])
        status = _price_status(p['standard_price'], p['list_price'])
        print(f"  {i:<4} {p['id']:<6} {p['name'][:32]:<32} {kode:<14} {modal:<12} {jual:<12} {status}")
        rows.append({
            'waktu': ts,
            'id_produk': p['id'],
            'nama_produk': p['name'],
            'kode_modal': kode,
            'harga_modal': p['standard_price'],
            'harga_jual': p['list_price'],
            'belum_diisi': status,
        })

    print_separator()

    csv_path = write_csv(rows, run_at, suffix='check')
    print(f'\n  Log disimpan: {csv_path}')
    print()
    print('=' * 72)


def cmd_fill(models, db, uid, password, args, run_at):
    """Isi standard_price dari kode_modal menggunakan chipper ABCDEFGHIY."""
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
        sys.exit(1)

    if not candidates:
        print('\n  Tidak ada produk yang perlu diperbarui. Selesai.')
        return

    to_update = []
    log_rows = []
    ts = run_at.strftime('%Y-%m-%d %H:%M:%S')

    for p in candidates:
        kode = (p['kode_modal'] or '').strip()
        if not kode:
            continue

        base = {
            'waktu': ts,
            'id_produk': p['id'],
            'nama_produk': p['name'],
            'kode_modal': kode,
            'modal_lama': 0,
            'modal_baru': '',
        }

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

        to_update.append({
            'id': p['id'],
            'name': p['name'],
            'kode_modal': kode,
            'cost': cost,
            'variant_ids': p['product_variant_ids'],
        })
        log_rows.append({**base, 'modal_baru': cost, 'status': 'PENDING', 'catatan': ''})

    skipped_rows = [r for r in log_rows if r['status'] == 'DILEWATI']
    if skipped_rows:
        print()
        print_separator()
        print(f'  DILEWATI ({len(skipped_rows)} produk):')
        print_separator()
        print(f"  {'Nama Produk':<36} {'Kode Modal':<14} Alasan")
        print_separator(char='·')
        for r in skipped_rows:
            print(f"  {r['nama_produk'][:36]:<36} {r['kode_modal']:<14} {r['catatan']}")

    if not to_update:
        print('\n  Tidak ada produk yang bisa di-decode dengan chipper ABCDEFGHIY.')
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
        print()
        print('=' * 72)
        return

    print()
    confirm = input('  Lanjutkan pengisian modal/cost? [y/N]: ').strip().lower()
    if confirm != 'y':
        print('\n  Dibatalkan.')
        return

    print()
    success = 0
    failed = 0
    pending = {r['id_produk']: r for r in log_rows if r['status'] == 'PENDING'}

    for p in to_update:
        try:
            models.execute_kw(
                db, uid, password,
                'product.product', 'write',
                [p['variant_ids'], {'standard_price': float(p['cost'])}],
            )
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
    print('=' * 72)
    print(f'  Selesai: {success} produk berhasil diperbarui', end='')
    print(f', {failed} gagal' if failed else '')
    print(f'  Log disimpan: {csv_path}')
    print('=' * 72)


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--check', action='store_true',
                        help='Cek produk dengan harga modal atau jual belum diisi (0 atau 1)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview saja, tidak tulis ke Odoo')
    parser.add_argument('--product', metavar='NAMA',
                        help='Filter nama produk (substring, tidak case-sensitive)')
    parser.add_argument('--id', dest='ids', metavar='ID', nargs='+', type=int,
                        help='Filter by ID produk (bisa lebih dari satu)')
    args = parser.parse_args()
    run_at = datetime.now()

    print()
    print('=' * 72)
    if args.check:
        print('    KODE MODAL DECODER  |  Cek Harga Belum Diisi')
    else:
        label = '  [DRY-RUN — tidak ada yang ditulis ke Odoo]' if args.dry_run else ''
        print(f'    KODE MODAL DECODER  |  Chipper ABCDEFGHIY{label}')
    print('=' * 72)

    cfg = load_config()
    url, db, username, password = cfg['url'], cfg['db'], cfg['username'], cfg['password']

    print(f'\n  Odoo : {url}')
    print(f'  DB   : {db}')
    print(f'  User : {username}')
    print('\n  Menghubungkan...', end=' ', flush=True)
    uid, models = connect_odoo(url, db, username, password)
    print(f'OK  (uid={uid})')

    if args.check:
        cmd_check(models, db, uid, password, args, run_at)
    else:
        cmd_fill(models, db, uid, password, args, run_at)


if __name__ == '__main__':
    main()
