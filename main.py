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
  python3 main.py --product "Sepatu" --dry-run
"""

import sys
import argparse
import configparser
import xmlrpc.client
from decoder import decode, is_abcdefghiy


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
    """Ambil produk: kode_modal terisi, standard_price kosong (= 0).

    name_filter : substring nama produk (case-insensitive)
    id_filter   : list of int product template IDs
    """
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
        {'fields': ['id', 'name', 'kode_modal', 'standard_price'], 'order': 'name asc'},
    )


def fmt_rp(amount: int) -> str:
    return 'Rp ' + f'{amount:,}'.replace(',', '.')


def print_separator(char='─', width=68):
    print('  ' + char * width)


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview saja, tidak tulis ke Odoo')
    parser.add_argument('--product', metavar='NAMA',
                        help='Filter nama produk (substring, tidak case-sensitive)')
    parser.add_argument('--id', dest='ids', metavar='ID', nargs='+', type=int,
                        help='Filter by ID produk (bisa lebih dari satu)')
    args = parser.parse_args()
    dry_run = args.dry_run

    print()
    print('=' * 72)
    label = '  [DRY-RUN — tidak ada yang ditulis ke Odoo]' if dry_run else ''
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
    skipped = []

    for p in candidates:
        kode = (p['kode_modal'] or '').strip()
        if not kode:
            continue
        if not is_abcdefghiy(kode):
            skipped.append((p['name'], kode, 'Bukan chipper ABCDEFGHIY'))
            continue
        cost = decode(kode)
        if cost is None:
            skipped.append((p['name'], kode, 'Format tidak dikenali'))
            continue
        if cost <= 0:
            skipped.append((p['name'], kode, 'Hasil decode = 0'))
            continue
        to_update.append({'id': p['id'], 'name': p['name'], 'kode_modal': kode, 'cost': cost})

    if skipped:
        print()
        print_separator()
        print(f'  DILEWATI ({len(skipped)} produk):')
        print_separator()
        print(f"  {'Nama Produk':<36} {'Kode Modal':<14} Alasan")
        print_separator(char='·')
        for name, kode, reason in skipped:
            print(f"  {name[:36]:<36} {kode:<14} {reason}")

    if not to_update:
        print('\n  Tidak ada produk yang bisa di-decode dengan chipper ABCDEFGHIY.')
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

    if dry_run:
        print()
        print('  Mode DRY-RUN: tidak ada perubahan yang ditulis ke Odoo.')
        print(f'  {len(to_update)} produk siap diperbarui jika dijalankan tanpa --dry-run.')
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
    for p in to_update:
        try:
            models.execute_kw(
                db, uid, password,
                'product.template', 'write',
                [[p['id']], {'standard_price': float(p['cost'])}],
            )
            print(f"  [OK]    {p['name']}  →  {fmt_rp(p['cost'])}")
            success += 1
        except Exception as e:
            print(f"  [GAGAL] {p['name']}  →  {e}")
            failed += 1

    print()
    print('=' * 72)
    print(f'  Selesai: {success} produk berhasil diperbarui', end='')
    print(f', {failed} gagal' if failed else '')
    print('=' * 72)


if __name__ == '__main__':
    main()
