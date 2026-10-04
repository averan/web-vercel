/*
 * Puente: el asistente ahora es un proyecto independiente (repo averan/asistente-ia).
 * Las páginas que todavía usan
 *   <script src="https://web-vercel-zeta-red.vercel.app/embed.js" defer></script>
 * siguen funcionando: este archivo carga el embed nuevo. Para integraciones nuevas usa directamente
 *   <script src="https://asistente-ia.andres-veran.workers.dev/embed.js" defer></script>
 */
(() => {
  const s = document.createElement('script');
  s.src = 'https://asistente-ia.andres-veran.workers.dev/embed.js';
  document.head.append(s);
})();
