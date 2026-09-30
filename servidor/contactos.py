#!/usr/bin/env python3
"""
Base de datos de solicitudes de contacto del asistente de Faena (SQLite).

La usa server.py para registrar las solicitudes que los visitantes validan en el chat.
También se puede usar sola para verlas:
    python3 contactos.py listar          (todas, las más recientes primero)
    python3 contactos.py ver FAE-0001    (detalle con la conversación)

Ruta de la base: CONTACTOS_DB (variable de entorno) o datos/contactos.db junto a este archivo.
"""
import json
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get('CONTACTOS_DB') or os.path.join(ROOT, 'datos', 'contactos.db')

# campo -> largo máximo
CAMPOS = {'nombre': 120, 'empresa': 160, 'cargo': 120, 'correo': 200, 'telefono': 60, 'interes': 200, 'necesidad': 3000}
OBLIGATORIOS = ('nombre', 'empresa', 'correo', 'necesidad')

SCHEMA = """
CREATE TABLE IF NOT EXISTS contactos (
    id           TEXT PRIMARY KEY,          -- FAE-0001
    fecha        TEXT NOT NULL,             -- ISO local
    estado       TEXT NOT NULL DEFAULT 'nuevo',
    nombre       TEXT NOT NULL,
    empresa      TEXT NOT NULL,
    cargo        TEXT,
    correo       TEXT NOT NULL,
    telefono     TEXT,
    interes      TEXT,
    necesidad    TEXT NOT NULL,
    conversacion TEXT,                      -- JSON [{rol, texto}]
    ip           TEXT
);
"""


def connect(path=DB_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def crear(db, datos, conversacion, ip):
    """Inserta una solicitud ya validada y devuelve (id, fecha). El número se asigna dentro de una transacción."""
    fecha = time.strftime('%Y-%m-%dT%H:%M:%S')
    db.execute('BEGIN IMMEDIATE')
    try:
        ultimo = db.execute("SELECT MAX(CAST(SUBSTR(id, 5) AS INTEGER)) FROM contactos").fetchone()[0] or 0
        cid = f'FAE-{ultimo + 1:04d}'
        db.execute(
            'INSERT INTO contactos (id, fecha, nombre, empresa, cargo, correo, telefono, interes, necesidad, conversacion, ip) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (cid, fecha, *(datos.get(k, '') for k in CAMPOS), json.dumps(conversacion, ensure_ascii=False), ip))
        db.execute('COMMIT')
    except Exception:
        db.execute('ROLLBACK')
        raise
    return cid, fecha


def listar(db):
    return db.execute('SELECT id, fecha, estado, nombre, empresa, correo, interes FROM contactos ORDER BY fecha DESC, id DESC').fetchall()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'listar'
    db = connect()
    if cmd == 'listar':
        filas = listar(db)
        if not filas:
            return print(f'No hay solicitudes de contacto todavía ({DB_PATH}).')
        for r in filas:
            print(f"{r['id']}  {r['fecha'][:16].replace('T', ' ')}  {r['estado']:<9}  {r['nombre']} · {r['empresa']} <{r['correo']}>"
                  + (f"  [{r['interes']}]" if r['interes'] else ''))
        return print(f'\n{len(filas)} solicitud(es) · {DB_PATH}')
    if cmd == 'ver' and len(sys.argv) > 2:
        r = db.execute('SELECT * FROM contactos WHERE id = ?', (sys.argv[2].upper(),)).fetchone()
        if not r:
            return print('No existe esa solicitud.')
        for k in ('id', 'fecha', 'estado', 'nombre', 'empresa', 'cargo', 'correo', 'telefono', 'interes', 'necesidad', 'ip'):
            print(f'{k:>10}: {r[k] or "-"}')
        print('\nConversación:')
        for m in json.loads(r['conversacion'] or '[]'):
            print(f"  [{m.get('rol')}] {m.get('texto')}\n")
        return None
    print(__doc__)


if __name__ == '__main__':
    main()
