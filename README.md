# web-vercel

Sitio de **Faena Growth Partner** (look & feel de faenacs.com): página estática en HTML + CSS, sin build, lista para publicar en [Vercel](https://vercel.com).

```
index.html      Página principal
404.html        Página de error (Vercel la usa automáticamente)
css/styles.css  Estilos (colores y tipografía de Faena)
img/            Logo (símbolo + wordmark) y favicons de Faena
vercel.json     URLs limpias y cabeceras de seguridad
assistant/      Widget del asistente (Faena-Bot)
config.js       Configuración del widget (nombre, saludo, sugerencias…)
embed.js        Integra el asistente en cualquier web con una línea
backend.js      Dirección del backend del asistente (la genera servidor/publicar.sh)
servidor/       Backend del asistente que corre en el Mac (Vercel no lo publica)
```

## Ver en local

```bash
python3 -m http.server 5190
```

Abre http://localhost:5190

## Publicar en Vercel

**Opción A — desde la terminal**

```bash
npx vercel login      # una sola vez
npx vercel            # vista previa (URL temporal)
npx vercel --prod     # producción
```

**Opción B — desde GitHub**
Sube el repositorio a GitHub y en vercel.com → *Add New… → Project* impórtalo.
Framework preset: **Other**, sin comando de build. Cada `git push` a `main` se publica solo.

## Asistente (Faena-Bot)

Asistente comercial: responde sobre los servicios de Faena y, cuando el visitante quiere
avanzar, arma una **solicitud de contacto** que él valida y envía con un botón.
El modelo corre en el Mac (oMLX), no en Vercel:

```
Navegador ── página ──► Vercel (index.html, assistant/, config.js, backend.js)
    └── chat (CORS) ──► túnel Cloudflare ──► servidor/server.py (Mac :5194) ──► oMLX :8000
                                                └─► servidor/datos/contactos.db (SQLite)
```

**Conectar el asistente** (el Mac debe estar encendido y oMLX en marcha):

```bash
./servidor/publicar.sh
```

Arranca el backend, abre un túnel y sube a GitHub la nueva dirección en `backend.js`;
Vercel se actualiza solo en ~30 s. Con **Ctrl+C** se desconecta y la web muestra
«asistente no disponible» con el correo de contacto.

**Ver y gestionar las solicitudes de contacto:** abre **http://localhost:5195** en este Mac
(se inicia junto con el backend; no se publica en internet). Muestra la lista con filtros por
estado y búsqueda, el detalle con la necesidad y la conversación con Faena-Bot, un botón para
responder por correo, y permite cambiar el estado (Nuevo → Contactado → En conversación →
Cerrado) y dejar notas en el historial.

También desde la terminal: `python3 servidor/contactos.py listar` y
`python3 servidor/contactos.py ver FAE-0001`.

**Configuración:**
- `servidor/.env` (no se sube a GitHub): API key de oMLX, orígenes permitidos y límites. Ver `servidor/.env.example`.
- `servidor/contexto.md`: lo que sabe el asistente y cómo responde. Los cambios se aplican sin reiniciar.
- `config.js`: nombre, saludo y preguntas sugeridas del widget.

**Seguridad:** la API key nunca sale del Mac; el prompt lo pone el servidor (el navegador no
puede cambiarlo); solo se aceptan peticiones desde la web de Vercel; hay límites de mensajes
por visitante, de generaciones simultáneas y de tokens; el chat no puede usar herramientas.

**Probar en local:** `python3 servidor/server.py` y `python3 -m http.server 5190`;
en `localhost:5190` el widget usa el backend local automáticamente.

## Integrar el asistente en otra página web

1. **Autoriza el dominio** en `servidor/.env` (exacto, con `https://`, sin barra final) y reinicia `./servidor/publicar.sh`:
   ```
   ALLOWED_ORIGINS=https://web-vercel-zeta-red.vercel.app,http://localhost:5190,https://www.ejemplo.com
   ```
   `ejemplo.com` y `www.ejemplo.com` son orígenes distintos. Sin este paso el widget aparece pero dice «Asistente no disponible».
2. **Pega una línea** antes de `</body>` (WordPress: plugin WPCode → footer; Shopify: `theme.liquid`; Wix/Squarespace: código personalizado del pie):
   ```html
   <script src="https://web-vercel-zeta-red.vercel.app/embed.js" defer></script>
   ```
3. **Opcional — personalizar** para ese sitio (antes de la línea anterior):
   ```html
   <script>window.FAENA_BOT = { greeting: '¡Hola!', suggestions: ['¿Cómo trabajan?'] };</script>
   ```
4. **Opcional — abrirlo desde un botón propio:** `<button onclick="omlxAssistant.open()">Hablar con Faena-Bot</button>`
   (también `omlxAssistant.close()`, `.toggle()` y `.reset()`).

`embed.js` carga los estilos, `backend.js` (dirección vigente del túnel), `config.js` y el widget desde Vercel,
así cada sitio recibe siempre la última versión sin copiar archivos. Si el sitio tiene una política CSP, debe permitir
scripts de `web-vercel-zeta-red.vercel.app` y conexiones a `*.trycloudflare.com`. Las solicitudes de todos los sitios
llegan a la misma página de gestión (http://localhost:5195).
