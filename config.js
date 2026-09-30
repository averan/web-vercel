// Configuración del asistente de Faena. Edita estos valores y vuelve a publicar.
// El prompt (qué sabe y cómo responde) NO está aquí: lo pone el servidor del Mac
// desde servidor/contexto.md, para que no sea público ni se pueda cambiar desde el navegador.
(() => {
  // backend.js (lo genera servidor/publicar.sh) trae la dirección del túnel hacia el Mac.
  // Al probar en local (localhost:5190) se usa el backend local directamente.
  const local = /^(localhost|127\.0\.0\.1)$/.test(location.hostname) ? 'http://localhost:5194' : '';
  const backend = window.FAENA_BACKEND || local;

  window.OMLX_ASSISTANT = {
    baseUrl: backend,
    // Sin backend (Mac apagado o sin publicar): el asistente muestra este aviso y no intenta conectar
    unavailable: !backend,
    unavailableMessage: 'En este momento el asistente no está disponible. Escríbenos a **soporte@faenacs.com** y te responderemos en menos de 48 horas hábiles.',

    assistantName: 'Asistente Faena',
    modelLabel: 'Faena-Bot',
    avatar: '/img/faena-symbol.png',
    greeting: 'Hola, soy Faena-Bot. Te cuento cómo ayudamos a empresas tecnológicas a crecer con estructura, o te conecto con un socio de Faena. ¿Qué desafío tiene hoy tu empresa?',
    suggestions: ['¿Qué es un ejecutivo fraccional?', '¿Cómo trabajan?', 'Quiero agendar una conversación'],

    // Solicitudes de contacto: el servidor del Mac las guarda con número FAE-…
    tickets: { endpoint: '/api/contactos' },
    attachments: false,
    footnote: 'Asistente virtual de Faena · puede cometer errores',

    maxTokens: 1024,
    temperature: 0.4,
    enableThinking: false,
  };
})();
