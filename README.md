# web-vercel

Sitio de **Faena Growth Partner** (look & feel de faenacs.com): página estática en HTML + CSS, sin build, lista para publicar en [Vercel](https://vercel.com).

```
index.html      Página principal
404.html        Página de error (Vercel la usa automáticamente)
css/styles.css  Estilos (colores y tipografía de Faena)
img/            Logo (símbolo + wordmark) y favicons de Faena
vercel.json     URLs limpias y cabeceras de seguridad
embed.js        Puente para integraciones antiguas del asistente (carga el embed nuevo)
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

El asistente ya no vive en este proyecto: es el proyecto independiente
[asistente-ia](https://github.com/averan/asistente-ia), que atiende a varios sitios. Esta página solo lo integra
con una línea, antes de `</body>`:

```html
<script src="https://asistente-ia.faenabot.stream/embed.js" defer></script>
```

Su configuración (nombre, saludo, sugerencias, colores, datos obligatorios) y lo que sabe de Faena están en el
servidor de `asistente-ia`, en `servidor/sitios/web-vercel-zeta-red.vercel.app.md`. Las solicitudes de contacto se
ven en la gestión de `asistente-ia` (http://localhost:5205, solo desde el Mac).

**Integraciones antiguas:** las páginas que todavía cargan `https://web-vercel-zeta-red.vercel.app/embed.js` siguen
funcionando, porque ese archivo ahora carga el embed nuevo. Para integraciones nuevas usa la línea de arriba.

El backend anterior (`servidor/`, `assistant/`, `config.js`, `backend.js`) quedó en el historial de git. En este Mac
`servidor/` conserva solo archivos locales que nunca se suben (`.env`, `datos/contactos.db` como respaldo de los
contactos ya importados en `asistente-ia`).
