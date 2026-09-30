#!/usr/bin/env python3
"""
Base de datos de solicitudes de contacto del asistente de Faena (SQLite).

La usan server.py (registrar las solicitudes que los visitantes validan en el chat) y
gestion.py (página de gestión en http://localhost:5195). También se puede usar sola:
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
    ip           TEXT,
    sitio        TEXT                       -- dominio de la página donde se hizo la solicitud
);
CREATE TABLE IF NOT EXISTS notas (          -- historial de gestión (cambios de estado y notas)
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contacto_id TEXT NOT NULL REFERENCES contactos(id),
    fecha       TEXT NOT NULL,
    texto       TEXT NOT NULL
);
"""
ESTADOS = {'nuevo': 'Nuevo', 'contactado': 'Contactado', 'en_curso': 'En conversación', 'cerrado': 'Cerrado'}


class Error(Exception):
    """Error que se muestra tal cual en la página de gestión."""


def connect(path=DB_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    if 'sitio' not in {r[1] for r in db.execute('PRAGMA table_info(contactos)')}:  # bases creadas antes de esta columna
        db.execute('ALTER TABLE contactos ADD COLUMN sitio TEXT')
        # hasta ahora el asistente solo estaba en la web de Faena en Vercel
        db.execute("UPDATE contactos SET sitio = 'web-vercel-zeta-red.vercel.app' WHERE sitio IS NULL")
    return db


def crear(db, datos, conversacion, ip, sitio=''):
    """Inserta una solicitud ya validada y devuelve (id, fecha). El número se asigna dentro de una transacción."""
    fecha = time.strftime('%Y-%m-%dT%H:%M:%S')
    db.execute('BEGIN IMMEDIATE')
    try:
        ultimo = db.execute("SELECT MAX(CAST(SUBSTR(id, 5) AS INTEGER)) FROM contactos").fetchone()[0] or 0
        cid = f'FAE-{ultimo + 1:04d}'
        db.execute(
            'INSERT INTO contactos (id, fecha, nombre, empresa, cargo, correo, telefono, interes, necesidad, conversacion, ip, sitio) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (cid, fecha, *(datos.get(k, '') for k in CAMPOS), json.dumps(conversacion, ensure_ascii=False), ip, sitio))
        db.execute('COMMIT')
    except Exception:
        db.execute('ROLLBACK')
        raise
    return cid, fecha


def listar(db, estado='', texto=''):
    sql, args = 'SELECT id, fecha, estado, nombre, empresa, cargo, correo, telefono, interes, sitio FROM contactos WHERE 1=1', []
    if estado:
        sql += ' AND estado = ?'; args.append(estado)
    if texto:
        sql += ' AND (nombre LIKE ? OR empresa LIKE ? OR correo LIKE ? OR interes LIKE ? OR necesidad LIKE ? OR sitio LIKE ?)'
        args += [f'%{texto}%'] * 6
    return db.execute(sql + ' ORDER BY fecha DESC, id DESC LIMIT 500', args).fetchall()


def conteo(db):
    return {r[0]: r[1] for r in db.execute('SELECT estado, COUNT(*) FROM contactos GROUP BY estado')}


def obtener(db, cid):
    r = db.execute('SELECT * FROM contactos WHERE id = ?', (cid.upper(),)).fetchone()
    if not r:
        raise Error(f'No existe la solicitud {cid}.')
    out = dict(r)
    out['conversacion'] = json.loads(r['conversacion'] or '[]')
    out['notas'] = [dict(n) for n in db.execute('SELECT fecha, texto FROM notas WHERE contacto_id = ? ORDER BY id', (r['id'],))]
    return out


def actualizar(db, cid, estado=None, nota=None):
    """Cambia el estado y/o agrega una nota. Cada cambio queda en el historial."""
    actual = obtener(db, cid)
    nota = (nota or '').strip()[:2000]
    if estado and estado not in ESTADOS:
        raise Error('Estado no válido.')
    if not (estado and estado != actual['estado']) and not nota:
        raise Error('Cambia el estado o escribe una nota.')
    fecha = time.strftime('%Y-%m-%dT%H:%M:%S')
    db.execute('BEGIN IMMEDIATE')
    try:
        if estado and estado != actual['estado']:
            db.execute('UPDATE contactos SET estado = ? WHERE id = ?', (estado, actual['id']))
            db.execute('INSERT INTO notas (contacto_id, fecha, texto) VALUES (?, ?, ?)',
                       (actual['id'], fecha, f'Estado: {ESTADOS.get(actual["estado"], actual["estado"])} → {ESTADOS[estado]}'))
        if nota:
            db.execute('INSERT INTO notas (contacto_id, fecha, texto) VALUES (?, ?, ?)', (actual['id'], fecha, nota))
        db.execute('COMMIT')
    except Exception:
        db.execute('ROLLBACK')
        raise
    return obtener(db, cid)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'listar'
    db = connect()
    if cmd == 'listar':
        filas = listar(db)
        if not filas:
            return print(f'No hay solicitudes de contacto todavía ({DB_PATH}).')
        for r in filas:
            print(f"{r['id']}  {r['fecha'][:16].replace('T', ' ')}  {r['estado']:<9}  {r['nombre']} · {r['empresa']} <{r['correo']}>"
                  + (f"  [{r['interes']}]" if r['interes'] else '') + (f"  · {r['sitio']}" if r['sitio'] else ''))
        return print(f'\n{len(filas)} solicitud(es) · {DB_PATH}')
    if cmd == 'ver' and len(sys.argv) > 2:
        r = db.execute('SELECT * FROM contactos WHERE id = ?', (sys.argv[2].upper(),)).fetchone()
        if not r:
            return print('No existe esa solicitud.')
        for k in ('id', 'fecha', 'estado', 'sitio', 'nombre', 'empresa', 'cargo', 'correo', 'telefono', 'interes', 'necesidad', 'ip'):
            print(f'{k:>10}: {r[k] or "-"}')
        print('\nConversación:')
        for m in json.loads(r['conversacion'] or '[]'):
            print(f"  [{m.get('rol')}] {m.get('texto')}\n")
        return None
    print(__doc__)


if __name__ == '__main__':
    main()
