#!/usr/bin/env python3
"""
Backend del asistente de Faena (corre en el Mac; la web está en Vercel).

La página publicada en Vercel llama directamente a este servidor a través del
túnel de Cloudflare (ver publicar.sh). Este servidor:
- Reenvía a oMLX solo lo que usa el asistente, con la API key del .env
  (nunca llega al navegador).
- Pone él mismo el prompt de sistema (contexto.md): se ignora el que envíe el
  navegador, así el túnel no sirve como chat genérico.
- Solo acepta peticiones de navegador desde los orígenes de ALLOWED_ORIGINS (CORS).
- Protege el Mac: límite de tamaño, de max_tokens, de generaciones simultáneas
  y de mensajes por minuto por visitante.
- Registra las solicitudes de contacto validadas (POST /api/contactos) en
  datos/contactos.db (ver contactos.py).

Uso:  python3 server.py              (configuración en .env, ver .env.example)
      python3 contactos.py listar    (solicitudes recibidas)
"""
import http.client
import json
import os
import re
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import contactos

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_env(path):
    env = {}
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env


ENV = {**load_env(os.path.join(ROOT, '.env')), **os.environ}
PORT = int(ENV.get('PORT', 5194))
ADMIN_PORT = int(ENV.get('ADMIN_PORT', 5195))  # página de gestión de contactos, solo local (0 = desactivada)
OMLX = urlsplit(ENV.get('OMLX_URL', 'http://127.0.0.1:8000'))
API_KEY = ENV.get('OMLX_API_KEY', '')
MAX_TOKENS = int(ENV.get('MAX_TOKENS', 1024))
MAX_CONCURRENT = int(ENV.get('MAX_CONCURRENT', 2))
RATE_PER_MIN = int(ENV.get('RATE_PER_MIN', 20))
CONTACTS_PER_MIN = int(ENV.get('CONTACTOS_PER_MIN', 5))
MAX_BODY = int(ENV.get('MAX_BODY_KB', 512)) * 1024   # el chat comercial no admite adjuntos
MAX_MESSAGES = 40                                     # historial que se envía al modelo
ALLOWED_ORIGINS = {o.strip().rstrip('/') for o in ENV.get(
    'ALLOWED_ORIGINS', 'https://web-vercel-zeta-red.vercel.app,http://localhost:5190').split(',') if o.strip()}
CONTEXT_FILE = os.path.join(ROOT, 'contexto.md')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

slots = threading.BoundedSemaphore(MAX_CONCURRENT)
hits = defaultdict(deque)
hits_lock = threading.Lock()
models_cache = {'t': None, 'ids': set()}
models_lock = threading.Lock()


def system_prompt():
    """Se lee en cada petición: los cambios en contexto.md se aplican sin reiniciar."""
    with open(CONTEXT_FILE, encoding='utf-8') as f:
        return f.read().strip()


def rate_limited(key, limit=RATE_PER_MIN):
    now = time.monotonic()
    with hits_lock:
        q = hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            return True
        q.append(now)
        return False


def upstream(method, path, body=None, timeout=600):
    conn = http.client.HTTPConnection(OMLX.hostname, OMLX.port or 80, timeout=timeout)
    headers = {'Content-Type': 'application/json'}
    if API_KEY:
        headers['Authorization'] = f'Bearer {API_KEY}'
    conn.request(method, path, body=body, headers=headers)
    return conn, conn.getresponse()


def get_json(path):
    conn, res = upstream('GET', path, timeout=15)
    try:
        raw = res.read()
    finally:
        conn.close()
    return res.status, json.loads(raw or b'{}')


def usable_models():
    """Modelos que un visitante puede usar: los ya cargados (o el predeterminado si no hay ninguno).
    Evita que alguien pida otro modelo y obligue a oMLX a cambiar el que está en memoria."""
    with models_lock:
        if models_cache['t'] is not None and time.monotonic() - models_cache['t'] < 30:
            return models_cache['ids']
        ids = set()
        try:
            _, status = get_json('/v1/models/status')
            ids |= {m.get('id') for m in status.get('models', []) if m.get('loaded')}
            if not ids:  # sin modelo en memoria: se admite el predeterminado (oMLX lo carga al preguntar)
                _, health = get_json('/health')
                if health.get('default_model'):
                    ids.add(health['default_model'])
        except (OSError, ValueError):
            pass
        models_cache.update(t=time.monotonic(), ids=ids)
        return ids


def clean_messages(messages):
    """Solo turnos de usuario/asistente con texto; el prompt de sistema lo pone el servidor."""
    out = []
    for m in messages[-MAX_MESSAGES:]:
        if isinstance(m, dict) and m.get('role') in ('user', 'assistant') and isinstance(m.get('content'), str):
            out.append({'role': m['role'], 'content': m['content'][:8000]})
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = 'FaenaAsistente'
    sys_version = ''

    # ---------- utilidades ----------
    def client_ip(self):
        return self.headers.get('CF-Connecting-IP') or self.client_address[0]

    def origin(self):
        return (self.headers.get('Origin') or '').rstrip('/')

    def origin_ok(self):
        """Sin Origin (curl, comprobaciones de publicar.sh) o con un origen de la lista blanca."""
        return not self.origin() or self.origin() in ALLOWED_ORIGINS

    def send_json(self, status, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def error(self, status, message):
        self.send_json(status, {'error': {'message': message}})

    def end_headers(self):
        if self.origin() in ALLOWED_ORIGINS:
            self.send_header('Access-Control-Allow-Origin', self.origin())
        self.send_header('Vary', 'Origin')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # solo se registran el chat y los contactos (ver do_POST)

    # ---------- rutas ----------
    def do_OPTIONS(self):  # preflight CORS
        if not self.origin() or self.origin() not in ALLOWED_ORIGINS:
            return self.error(403, 'Origen no permitido')
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Max-Age', '600')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        if not self.origin_ok():
            return self.error(403, 'Origen no permitido')
        path = urlsplit(self.path).path
        if path in ('/health', '/v1/models/status'):
            return self.proxy_get(path)
        self.error(404, 'No encontrado')

    def do_POST(self):
        if not self.origin_ok():
            return self.error(403, 'Origen no permitido')
        path = urlsplit(self.path).path
        if path == '/api/contactos':
            return self.create_contact()
        if path != '/v1/chat/completions':
            return self.error(404, 'No encontrado')
        ip, t0 = self.client_ip(), time.time()
        status = self.proxy_chat(ip)
        print(f'{time.strftime("%H:%M:%S")}  chat  {ip:<15}  {status}  {time.time() - t0:5.1f}s', flush=True)

    def do_PUT(self):
        self.error(405, 'Método no permitido')

    do_DELETE = do_PATCH = do_PUT

    # ---------- solicitudes de contacto ----------
    def create_contact(self):
        ip = self.client_ip()
        length = int(self.headers.get('Content-Length') or 0)
        if length <= 0 or length > MAX_BODY:
            return self.error(400, 'Solicitud no válida.')
        if rate_limited('contacto:' + ip, CONTACTS_PER_MIN):
            return self.error(429, 'Has enviado demasiadas solicitudes seguidas. Espera un minuto.')
        try:
            data = json.loads(self.rfile.read(length))
            assert isinstance(data, dict)
        except (ValueError, AssertionError):
            return self.error(400, 'Solicitud no válida.')
        datos = {k: str(data.get(k) or '').strip()[:n] for k, n in contactos.CAMPOS.items()}
        faltan = [k for k in contactos.OBLIGATORIOS if not datos[k] or re.match(r'no informad', datos[k], re.I)]
        if faltan:
            return self.error(400, 'Faltan datos obligatorios: ' + ', '.join(faltan) + '.')
        if not EMAIL_RE.match(datos['correo']):
            return self.error(400, 'El correo no parece válido. Corrígelo y vuelve a enviar.')
        conv = data.get('conversacion') if isinstance(data.get('conversacion'), list) else []
        conversacion = [{'rol': str(m.get('role', ''))[:20], 'texto': str(m.get('content', ''))[:4000]}
                        for m in conv[-MAX_MESSAGES:] if isinstance(m, dict)]
        try:
            db = contactos.connect()
            try:
                cid, fecha = contactos.crear(db, datos, conversacion, ip)
            finally:
                db.close()
        except Exception as e:  # noqa: BLE001 — cualquier fallo del registro se informa igual al visitante
            print(f'{time.strftime("%H:%M:%S")}  CONTACTO ERROR  {e}', flush=True)
            return self.error(503, 'No se pudo registrar la solicitud en este momento. Inténtalo en unos minutos.')
        print(f'{time.strftime("%H:%M:%S")}  CONTACTO {cid}  {datos["nombre"]} · {datos["empresa"]} <{datos["correo"]}>', flush=True)
        self.send_json(201, {'id': cid, 'fecha': fecha})

    # ---------- proxy hacia oMLX ----------
    def proxy_get(self, path):
        try:
            status, data = get_json(path)
        except (OSError, ValueError):
            return self.error(502, 'El asistente no está disponible en este momento. Inténtalo en unos minutos.')
        if status != 200:
            return self.error(status, 'El asistente respondió con un error. Inténtalo de nuevo.')
        if path == '/v1/models/status':
            # no exponer rutas locales, tamaños ni configuración interna
            data = {'models': [{'id': m.get('id'), 'loaded': m.get('loaded'), 'model_type': m.get('model_type')}
                               for m in data.get('models', [])]}
        else:
            data = {'status': data.get('status'), 'default_model': data.get('default_model')}
        self.send_json(200, data)

    def proxy_chat(self, ip):
        length = int(self.headers.get('Content-Length') or 0)
        if length <= 0:
            self.error(400, 'Petición vacía.'); return 400
        if length > MAX_BODY:
            self.error(413, 'La conversación es demasiado larga. Empieza una nueva.'); return 413
        if rate_limited(ip):
            self.error(429, 'Has enviado demasiados mensajes seguidos. Espera un minuto e inténtalo de nuevo.'); return 429
        try:
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict) or not isinstance(body.get('messages'), list):
                raise ValueError
        except ValueError:
            self.error(400, 'Petición no válida.'); return 400
        messages = clean_messages(body['messages'])
        if not messages or messages[-1]['role'] != 'user':
            self.error(400, 'Petición no válida.'); return 400
        if body.get('model') not in usable_models():
            models_cache['t'] = None  # puede que el modelo haya cambiado: se vuelve a consultar la próxima vez
            self.error(404, 'El asistente se está actualizando. Inténtalo de nuevo.'); return 404
        # solo pasan los parámetros conocidos; nunca herramientas ni otro prompt de sistema
        payload = {
            'model': body['model'],
            'messages': [{'role': 'system', 'content': system_prompt()}] + messages,
            'stream': bool(body.get('stream', True)),
            'max_tokens': min(int(body.get('max_tokens') or MAX_TOKENS), MAX_TOKENS),
            'temperature': min(max(float(body.get('temperature') or 0.4), 0.0), 1.0),
            'enable_thinking': False,
            'tool_choice': 'none',
        }

        if not slots.acquire(blocking=False):
            self.error(503, 'El asistente está ocupado atendiendo otras consultas. Inténtalo en unos segundos.'); return 503
        conn = None
        try:
            try:
                conn, res = upstream('POST', '/v1/chat/completions', json.dumps(payload).encode())
            except OSError:
                self.error(502, 'El asistente no está disponible en este momento. Inténtalo en unos minutos.'); return 502
            self.send_response(res.status)
            self.send_header('Content-Type', res.getheader('Content-Type', 'application/json'))
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('X-Accel-Buffering', 'no')
            self.send_header('Connection', 'close')
            self.end_headers()
            # reenvío en streaming: cada bloque sale en cuanto llega de oMLX
            while True:
                chunk = res.read1(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
            return res.status
        except (BrokenPipeError, ConnectionResetError):
            return 499  # el visitante cerró la conexión: se corta también la generación
        finally:
            if conn:
                conn.close()
            slots.release()


def main():
    if not API_KEY:
        print('Aviso: OMLX_API_KEY no está definida en .env; se llamará a oMLX sin clave.')
    system_prompt()  # falla al arrancar si falta contexto.md
    srv = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    srv.daemon_threads = True
    print(f'Backend del asistente en http://localhost:{PORT}  →  oMLX en {OMLX.geturl()}  '
          f'(máx. {MAX_CONCURRENT} simultáneas, {RATE_PER_MIN} msg/min por visitante, max_tokens {MAX_TOKENS})', flush=True)
    print(f'Orígenes permitidos: {", ".join(sorted(ALLOWED_ORIGINS))}', flush=True)
    if ADMIN_PORT:
        import gestion  # página de gestión de contactos: puerto aparte, nunca publicado por el túnel
        try:
            gestion.start(ADMIN_PORT)
            print(f'Gestión de contactos en http://localhost:{ADMIN_PORT}  (solo desde este Mac)', flush=True)
        except OSError:
            print(f'Aviso: el puerto {ADMIN_PORT} está ocupado; la página de gestión no se inició.', flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
