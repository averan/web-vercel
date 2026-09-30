/*
 * Faena-Bot — integra el asistente en cualquier página web con una sola línea:
 *
 *   <script src="https://web-vercel-zeta-red.vercel.app/embed.js" defer></script>
 *
 * Carga, en orden y desde el mismo sitio que este archivo: los estilos del widget,
 * backend.js (dirección vigente del túnel hacia el Mac), config.js y el widget.
 * El dominio de la página debe estar autorizado en ALLOWED_ORIGINS (servidor/.env).
 *
 * Personalizar (opcional), definiéndolo ANTES de esta línea:
 *   <script>window.FAENA_BOT = { greeting: '¡Hola!', suggestions: ['¿Cómo trabajan?'] };</script>
 * Abrir desde un botón propio:  <button onclick="omlxAssistant.open()">Hablar con Faena-Bot</button>
 */
(() => {
  if (window.__faenaBotEmbed) return; // evita cargarlo dos veces si se pega el código repetido
  window.__faenaBotEmbed = true;

  const base = new URL('.', document.currentScript?.src || location.href).href; // carpeta de este archivo
  const css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = base + 'assistant/assistant.css';
  document.head.append(css);

  const load = src => new Promise((ok, ko) => {
    const s = document.createElement('script');
    s.src = src;
    s.async = false;
    s.onload = ok;
    s.onerror = () => ko(new Error('no se pudo cargar ' + src));
    document.head.append(s);
  });

  (async () => {
    try {
      await load(base + 'backend.js');
      await load(base + 'config.js');
      if (window.FAENA_BOT && typeof window.FAENA_BOT === 'object') Object.assign(window.OMLX_ASSISTANT, window.FAENA_BOT);
      await load(base + 'assistant/assistant.js');
    } catch (e) {
      console.warn('Faena-Bot:', e.message);
    }
  })();
})();
