#!/usr/bin/env python3
"""
Backend del asistente de Faena (corre en el Mac; la web está en Vercel).

La página publicada en Vercel llama directamente a este servidor a través del
túnel de Cloudflare (ver publicar.sh). Este servidor:
- Reenvía a oMLX solo lo que usa el asistente, con la API key del .env
  (nunca llega al navegador).
- Pone él mismo el prompt de sistema: sitios/<dominio>.md (contexto de cada sitio que
  integra el widget) o contexto.md (Faena), más reglas-contacto.md, común a todos.
  Se ignora el que envíe el navegador, así el túnel no sirve como chat genérico.
- Solo acepta peticiones de navegador desde los orígenes de ALLOWED_ORIGINS o con un
  archivo en sitios/ (CORS).
- Protege el Mac: límite de tamaño, de max_tokens, de generaciones simultáneas
  y de mensajes por minuto por visitante.
- Registra las solicitudes de contacto validadas (POST /api/contactos) en
  datos/contactos.db (ver contactos.py).

Uso:  python3 server.py              (configuración en .env, ver .env.example)
      python3 contactos.py listar    (solicitudes recibidas)
"""
import base64
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
MAX_BODY = int(ENV.get('MAX_BODY_MB', 25)) * 1024 * 1024   # mensajes con imágenes y documentos
MAX_MESSAGES = 40                                     # historial que se envía al modelo
MAX_TEXT = 100000                                     # caracteres por mensaje (incluye documentos extraídos)
MAX_IMAGES = 6                                        # imágenes por mensaje
IMAGE_URL_RE = re.compile(r'^data:image/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+$')
# archivos que se guardan con la solicitud de contacto
MAX_FILES = 10
MAX_FILE = int(ENV.get('MAX_ADJUNTO_MB', 10)) * 1024 * 1024
MAX_FILES_TOTAL = int(ENV.get('MAX_ADJUNTOS_TOTAL_MB', 25)) * 1024 * 1024
CONTACT_MAX_BODY = MAX_FILES_TOTAL * 4 // 3 + 2 * 1024 * 1024   # base64 + datos de la solicitud
# texto y código: se guardan como text/plain (nunca se ejecutan ni se muestran como HTML)
TEXT_EXTS = {'txt', 'log', 'out', 'err', 'trace', 'csv', 'tsv', 'json', 'xml', 'md', 'markdown', 'yaml', 'yml', 'ini', 'toml',
             'sql', 'conf', 'cfg', 'html', 'htm', 'css', 'js', 'jsx', 'ts', 'tsx', 'py', 'java', 'c', 'h', 'cpp', 'cs', 'go',
             'rs', 'rb', 'php', 'swift', 'kt', 'sh', 'tex', 'rtf'}
ALLOWED_ORIGINS = {o.strip().rstrip('/') for o in ENV.get(
    'ALLOWED_ORIGINS', 'https://web-vercel-zeta-red.vercel.app,http://localhost:5190').split(',') if o.strip()}
CONTEXT_FILE = os.path.join(ROOT, 'contexto.md')          # contexto predeterminado (Faena)
COMMON_FILE = os.path.join(ROOT, 'reglas-contacto.md')   # formato de la solicitud y reglas: se agrega a todos
SITES_DIR = os.path.join(ROOT, 'sitios')                 # un contexto por sitio: sitios/www.ejemplo.com.md
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
EMAIL_IN_TEXT = re.compile(r'[^@\s]+@[^@\s]+\.[a-z]{2,}', re.I)
# Recordatorio que se agrega (solo hacia el modelo) al mensaje del visitante que trae un correo:
# el modelo pequeño tiende a pedir datos opcionales en vez de presentar la solicitud.
CONTACT_NUDGE = ('\n\n[Nota interna del sistema, no la menciones: este mensaje trae el correo del visitante. '
                 'Si ya tienes su nombre y empresa, responde AHORA solo con el bloque «📋 Solicitud de contacto lista '
                 'para enviar» (cargo y teléfono: "no informado" si no los dio; el área la eliges tú), sin hacer preguntas.]')
# Variante para sitios que aceptan cualquier medio de contacto (al_menos_uno en su archivo de sitios/)
CONTACT_NUDGE_ANY = ('\n\n[Nota interna del sistema, no la menciones: este mensaje trae un medio de contacto del visitante. '
                     'Responde AHORA solo con el bloque «📋 Solicitud de contacto lista para enviar», con "no informado" '
                     'en los datos que falten, sin hacer preguntas.]')
PHONE_IN_TEXT = re.compile(r'\+?\d[\d\s().-]{6,}\d')

slots = threading.BoundedSemaphore(MAX_CONCURRENT)
hits = defaultdict(deque)
hits_lock = threading.Lock()
models_cache = {'t': None, 'ids': set()}
models_lock = threading.Lock()


def site_file(origin):
    """Contexto propio del sitio (sitios/<dominio>.md) o None. Solo https, salvo localhost para pruebas."""
    url = urlsplit(origin or '')
    host = (url.netloc or '').lower()
    local = re.fullmatch(r'(localhost|127\.0\.0\.1)(:\d+)?', host)
    if not re.fullmatch(r'[a-z0-9.-]+(:\d+)?', host) or not (url.scheme == 'https' or (local and url.scheme == 'http')):
        return None
    path = os.path.join(SITES_DIR, host.replace(':', '_') + '.md')
    return path if os.path.isfile(path) else None


def origin_allowed(origin):
    """Autorizado si está en ALLOWED_ORIGINS o si tiene su archivo en sitios/ (no hace falta reiniciar)."""
    return bool(origin) and (origin in ALLOWED_ORIGINS or site_file(origin) is not None)


def site_config(origin):
    """(contexto, reglas) del sitio. El archivo puede empezar con un bloque de configuración:
        ---
        obligatorios: necesidad
        al_menos_uno: correo, telefono, otro
        reglas_comunes: no
        ---
    Sin bloque: obligatorios de Faena (nombre, empresa, correo, necesidad) y con reglas comunes."""
    with open(site_file(origin) or CONTEXT_FILE, encoding='utf-8') as f:
        text = f.read()
    rules = {'obligatorios': list(contactos.OBLIGATORIOS), 'al_menos_uno': [], 'reglas_comunes': True}
    m = re.match(r'---\s*\n(.*?)\n---\s*\n', text, re.S)
    if m:
        text = text[m.end():]
        for line in m.group(1).splitlines():
            key, _, value = (x.strip() for x in line.partition(':'))
            if key in ('obligatorios', 'al_menos_uno'):
                rules[key] = [c for c in (x.strip() for x in value.split(',')) if c in contactos.CAMPOS]
            elif key == 'reglas_comunes':
                rules[key] = value.lower() not in ('no', 'false', '0')
    return text.strip(), rules


def system_prompt(origin=''):
    """Contexto del sitio (o el predeterminado) + reglas comunes si corresponde. Se leen en cada
    consulta: los cambios se aplican sin reiniciar."""
    text, rules = site_config(origin)
    if rules['reglas_comunes']:
        with open(COMMON_FILE, encoding='utf-8') as f:
            text += '\n\n' + f.read().strip()
    return text


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


def clean_content(content):
    """Texto, o lista de partes de texto e imágenes (data:image/…;base64); cualquier otra cosa se descarta."""
    if isinstance(content, str):
        return content[:MAX_TEXT]
    if not isinstance(content, list):
        return None
    parts, images = [], 0
    for p in content:
        if not isinstance(p, dict):
            continue
        if p.get('type') == 'text' and isinstance(p.get('text'), str):
            parts.append({'type': 'text', 'text': p['text'][:MAX_TEXT]})
        elif p.get('type') == 'image_url' and images < MAX_IMAGES:
            url = (p.get('image_url') or {}).get('url') if isinstance(p.get('image_url'), dict) else None
            if isinstance(url, str) and IMAGE_URL_RE.match(url):
                parts.append({'type': 'image_url', 'image_url': {'url': url}})
                images += 1
    return parts or None


def content_text(content):
    """Lo que escribió el visitante, sin el texto de los documentos adjuntos (que pueden traer correos o
    teléfonos ajenos y no deben activar el recordatorio de la solicitud de contacto)."""
    text = content if isinstance(content, str) else ' '.join(p['text'] for p in content if p['type'] == 'text')
    return re.sub(r'<documento\b[^>]*>.*?</documento>', ' ', text, flags=re.S)


def with_note(content, note):
    """Agrega una nota al texto del mensaje (sea texto simple o lista con imágenes)."""
    if isinstance(content, str):
        return content + note
    parts = [dict(p) for p in content]
    for p in parts:
        if p['type'] == 'text':
            p['text'] += note
            return parts
    return [{'type': 'text', 'text': note.strip()}] + parts


def clean_messages(messages):
    """Solo turnos de usuario/asistente (texto, e imágenes en los del usuario); el prompt de sistema lo pone el servidor."""
    out = []
    for m in messages[-MAX_MESSAGES:]:
        if not isinstance(m, dict) or m.get('role') not in ('user', 'assistant'):
            continue
        content = clean_content(m.get('content')) if m['role'] == 'user' else (
            m['content'][:MAX_TEXT] if isinstance(m.get('content'), str) else None)
        if content:
            out.append({'role': m['role'], 'content': content})
    return out


def sniff_type(data, name):
    """Tipo MIME según el contenido real del archivo (no el que declara el navegador); None si no se admite."""
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    if data.startswith(b'%PDF-'):
        return 'application/pdf'
    if data.startswith(b'PK\x03\x04') and ext == 'docx':
        return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    if data.startswith(b'PK\x03\x04') and ext == 'xlsx':
        return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    if data.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1') and ext == 'xls':
        return 'application/vnd.ms-excel'
    if (ext in TEXT_EXTS or re.fullmatch(r'log\.\d+', ext)) and b'\x00' not in data[:8192]:
        return 'text/plain'
    return None


def parse_files(raw):
    """Valida los archivos de la solicitud. Devuelve (lista [{nombre, tipo, datos}], None) o (None, mensaje de error)."""
    if raw is None:
        return [], None
    if not isinstance(raw, list) or len(raw) > MAX_FILES:
        return None, f'Puedes adjuntar como máximo {MAX_FILES} archivos por solicitud.'
    files, total = [], 0
    for f in raw:
        if not isinstance(f, dict):
            return None, 'Archivo no válido.'
        name = os.path.basename(str(f.get('nombre') or 'archivo').replace('\\', '/'))[:200] or 'archivo'
        try:
            data = base64.b64decode(str(f.get('contenido_base64') or ''), validate=True)
        except ValueError:
            return None, f'El archivo «{name}» está dañado.'
        if not data:
            continue
        if len(data) > MAX_FILE:
            return None, f'«{name}» supera el máximo de {MAX_FILE // 1048576} MB por archivo.'
        total += len(data)
        if total > MAX_FILES_TOTAL:
            return None, f'Los archivos superan el máximo de {MAX_FILES_TOTAL // 1048576} MB por solicitud.'
        mime = sniff_type(data, name)
        if not mime:
            return None, f'«{name}» no es un tipo de archivo admitido.'
        files.append({'nombre': name, 'tipo': mime, 'datos': data})
    return files, None


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
        return not self.origin() or origin_allowed(self.origin())

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
        if origin_allowed(self.origin()):
            self.send_header('Access-Control-Allow-Origin', self.origin())
        self.send_header('Vary', 'Origin')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # solo se registran el chat y los contactos (ver do_POST)

    # ---------- rutas ----------
    def do_OPTIONS(self):  # preflight CORS
        if not origin_allowed(self.origin()):
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
    def check_contact(self, ip):
        """Valida la solicitud. Devuelve (status, mensaje de error) o (201, None) y deja los datos en self._contact."""
        length = int(self.headers.get('Content-Length') or 0)
        if length <= 0:
            return 400, 'Solicitud no válida.'
        if length > CONTACT_MAX_BODY:
            return 413, f'Los archivos superan el máximo de {MAX_FILES_TOTAL // 1048576} MB por solicitud.'
        if rate_limited('contacto:' + ip, CONTACTS_PER_MIN):
            return 429, 'Has enviado demasiadas solicitudes seguidas. Espera un minuto.'
        try:
            data = json.loads(self.rfile.read(length))
            assert isinstance(data, dict)
        except (ValueError, AssertionError):
            return 400, 'Solicitud no válida.'
        rules = site_config(self.origin())[1]
        datos = {k: str(data.get(k) or '').strip()[:n] for k, n in contactos.CAMPOS.items()}
        for k, v in datos.items():  # «no informado» cuenta como vacío
            if re.match(r'no informad', v, re.I):
                datos[k] = ''
        faltan = [k for k in rules['obligatorios'] if not datos[k]]
        if faltan:
            return 400, 'Faltan datos obligatorios: ' + ', '.join(faltan) + '.'
        if rules['al_menos_uno'] and not any(datos[k] for k in rules['al_menos_uno']):
            return 400, 'Indica al menos un medio de contacto (correo, teléfono u otro).'
        if datos['correo'] and not EMAIL_RE.match(datos['correo']):
            return 400, 'El correo no parece válido. Corrígelo y vuelve a enviar.'
        files, problem = parse_files(data.get('archivos'))
        if problem:
            return 400, problem
        self._contact = (data, datos, files)
        return 201, None

    def create_contact(self):
        ip = self.client_ip()
        status, problem = self.check_contact(ip)
        if problem:  # se registra el rechazo para poder diagnosticar envíos que no llegan
            print(f'{time.strftime("%H:%M:%S")}  CONTACTO RECHAZADO  {ip:<15}  {status}  {problem}', flush=True)
            return self.error(status, problem)
        data, datos, files = self._contact
        conv = data.get('conversacion') if isinstance(data.get('conversacion'), list) else []
        conversacion = [{'rol': str(m.get('role', ''))[:20], 'texto': str(m.get('content', ''))[:4000],
                         'adjuntos': [str(a)[:200] for a in (m.get('adjuntos') or [])][:10] if isinstance(m.get('adjuntos'), list) else []}
                        for m in conv[-MAX_MESSAGES:] if isinstance(m, dict)]
        try:
            db = contactos.connect()
            try:
                cid, fecha = contactos.crear(db, datos, conversacion, ip, urlsplit(self.origin()).netloc, files)
            finally:
                db.close()
        except Exception as e:  # noqa: BLE001 — cualquier fallo del registro se informa igual al visitante
            print(f'{time.strftime("%H:%M:%S")}  CONTACTO ERROR  {e}', flush=True)
            return self.error(503, 'No se pudo registrar la solicitud en este momento. Inténtalo en unos minutos.')
        print(f'{time.strftime("%H:%M:%S")}  CONTACTO {cid}  {datos["nombre"]} · {datos["empresa"]} <{datos["correo"]}>'
              f'  [{urlsplit(self.origin()).netloc or "-"}]' + (f'  📎 {len(files)}' if files else ''), flush=True)
        self.send_json(201, {'id': cid, 'fecha': fecha, 'adjuntos': len(files)})

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
            self.error(413, 'El mensaje o los archivos son demasiado grandes.'); return 413
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
        any_contact = bool(site_config(self.origin())[1]['al_menos_uno'])
        last = content_text(messages[-1]['content'])
        if EMAIL_IN_TEXT.search(last) or (any_contact and PHONE_IN_TEXT.search(last)):
            messages[-1] = {'role': 'user', 'content': with_note(messages[-1]['content'], CONTACT_NUDGE_ANY if any_contact else CONTACT_NUDGE)}
        if body.get('model') not in usable_models():
            models_cache['t'] = None  # puede que el modelo haya cambiado: se vuelve a consultar la próxima vez
            self.error(404, 'El asistente se está actualizando. Inténtalo de nuevo.'); return 404
        # solo pasan los parámetros conocidos; nunca herramientas ni otro prompt de sistema
        payload = {
            'model': body['model'],
            'messages': [{'role': 'system', 'content': system_prompt(self.origin())}] + messages,
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
    system_prompt()  # falla al arrancar si falta contexto.md o reglas-contacto.md
    srv = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    srv.daemon_threads = True
    print(f'Backend del asistente en http://localhost:{PORT}  →  oMLX en {OMLX.geturl()}  '
          f'(máx. {MAX_CONCURRENT} simultáneas, {RATE_PER_MIN} msg/min por visitante, max_tokens {MAX_TOKENS})', flush=True)
    sites = sorted(f[:-3].replace('_', ':') for f in os.listdir(SITES_DIR) if f.endswith('.md') and not f.startswith('_')) \
        if os.path.isdir(SITES_DIR) else []
    print(f'Orígenes permitidos: {", ".join(sorted(ALLOWED_ORIGINS))}', flush=True)
    print(f'Sitios con contexto propio (sitios/): {", ".join(sites) or "ninguno"}', flush=True)
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
