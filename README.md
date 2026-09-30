# web-vercel

Página web estática (HTML + CSS, sin build) lista para publicar en [Vercel](https://vercel.com).

```
index.html      Página principal
404.html        Página de error (Vercel la usa automáticamente)
css/styles.css  Estilos (modo claro/oscuro automático)
favicon.svg     Icono
vercel.json     URLs limpias y cabeceras de seguridad
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
