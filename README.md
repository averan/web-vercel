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
- `servidor/contexto.md`: lo que sabe el asistente de Faena y cómo responde; `servidor/sitios/`: el de cada sitio integrado;
  `servidor/reglas-contacto.md`: formato de la solicitud y reglas comunes. Los cambios se aplican sin reiniciar.
- `config.js`: nombre, saludo y preguntas sugeridas del widget.

**Seguridad:** la API key nunca sale del Mac; el prompt lo pone el servidor (el navegador no
puede cambiarlo); solo se aceptan peticiones desde la web de Vercel; hay límites de mensajes
por visitante, de generaciones simultáneas y de tokens; el chat no puede usar herramientas.

**Probar en local:** `python3 servidor/server.py` y `python3 -m http.server 5190`;
en `localhost:5190` el widget usa el backend local automáticamente.

## Integrar el asistente en otra página web

1. **Crea el contexto del sitio** (esto también lo autoriza; no hace falta reiniciar):
   ```bash
   cp servidor/sitios/_plantilla.md servidor/sitios/www.ejemplo.com.md
   ```
   El nombre del archivo es el dominio exacto (`www.ejemplo.com` y `ejemplo.com` son distintos; si el sitio usa ambos,
   crea los dos archivos). Edítalo con la identidad, los servicios, las preguntas frecuentes y el contacto de esa empresa.
   Solo se aceptan sitios `https://`. Estos archivos no se suben a GitHub.
2. **Pega una línea** antes de `</body>` (WordPress: plugin WPCode → footer; Shopify: `theme.liquid`; Wix/Squarespace: código personalizado del pie):
   ```html
   <script src="https://web-vercel-zeta-red.vercel.app/embed.js" defer></script>
   ```
3. **Personaliza lo visible** (antes de la línea anterior):
   ```html
   <script>
     window.FAENA_BOT = {
       assistantName: 'Asistente Ejemplo', modelLabel: 'Ejemplo-Bot',
       greeting: '¡Hola! ¿En qué te ayudo?',
       suggestions: ['¿Qué servicios tienen?', 'Quiero que me contacten'],
       contactConfirmation: 'Te escribiremos a {correo} a la brevedad.',
       unavailableMessage: 'El asistente no está disponible. Escríbenos a contacto@ejemplo.com.',
       footnote: 'Asistente virtual de Ejemplo'
     };
   </script>
   ```
4. **Opcional — abrirlo desde un botón propio:** `<button onclick="omlxAssistant.open()">Hablar con el asistente</button>`
   (también `omlxAssistant.close()`, `.toggle()` y `.reset()`).

**Qué es de cada sitio y qué es común:**

| Dónde | Qué define |
|---|---|
| `servidor/sitios/<dominio>.md` | Qué sabe el asistente y cómo habla (identidad, servicios, precios, FAQ, reglas propias). Sin archivo se usa `servidor/contexto.md` (Faena) |
| `servidor/reglas-contacto.md` | Común a todos: formato de la solicitud de contacto y reglas generales (no editar el formato: el botón «Enviar solicitud» depende de él) |
| `window.FAENA_BOT` en la página | Nombre, saludo, sugerencias, confirmación y avisos que ve el visitante |

Los cambios en los `.md` se aplican en la siguiente consulta, sin reiniciar. Las solicitudes de todos los sitios llegan
a la misma página de gestión (http://localhost:5195), con una columna **Sitio** que indica su origen.

`embed.js` carga los estilos, `backend.js` (dirección vigente del túnel), `config.js` y el widget desde Vercel, así cada
sitio recibe siempre la última versión. Si el sitio tiene una política CSP, debe permitir scripts de
`web-vercel-zeta-red.vercel.app` y conexiones a `*.trycloudflare.com`. Alternativa a los archivos de `sitios/`: agregar
el dominio a `ALLOWED_ORIGINS` en `servidor/.env` (usa el contexto de Faena y requiere reiniciar `publicar.sh`).
