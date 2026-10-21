import type { NextConfig } from 'next';

import packageJson from './package.json';

const nextConfig: NextConfig = {
  // En producción la app se distribuye como bundle estático servido por Electron.
  // `output: 'export'` produce `ui/out/` con HTML/CSS/JS planos.
  // En dev (`pnpm dev`) Next sigue corriendo en localhost:3001 normalmente —
  // esta opción solo afecta `pnpm build`.
  output: 'export',

  // El bundle empacado se sirve por un protocolo propio `app://` registrado en
  // el main de Electron (ver desktop/main.js), NO por `file://`. Eso da un
  // ORIGEN real con raíz bien definida, así que los paths absolutos que emite
  // Next (`/_next/static/...`, `/icon.png`) y la navegación del router
  // (`/empresas`, `/comprobantes`, ...) resuelven correctamente contra esa raíz
  // en CUALQUIER ruta (incluidas subrutas como `/comprobantes/cfdi/`).
  //
  // Por eso NO usamos `assetPrefix: './'`: el prefijo relativo solo funcionaba
  // para el index plano y se rompía al navegar a subrutas (`./_next` resolvía
  // contra la carpeta de la subruta). Con `app://` los absolutos son correctos.

  // `trailingSlash: true` exporta cada ruta como `<ruta>/index.html` (uniforme)
  // y hace que `next/link` normalice `/empresas` → `/empresas/`, lo que
  // simplifica el handler del protocolo (un request a `/empresas/` mapea a
  // `empresas/index.html`).
  //
  // EXCEPTO en el build web (Vercel): ahí el trailing slash hace que Vercel
  // responda 308 (`/api/x` → `/api/x/`) ANTES de aplicar los rewrites de
  // vercel.json, rompiendo el proxy hacia el legacy (los desktops instalados
  // pegan a /api/desktop/* sin slash, y Stripe no sigue redirects en
  // webhooks). En web Vercel resuelve `/ruta` → `ruta.html` sin redirect.
  trailingSlash: process.env.NEXT_PUBLIC_MODO_WEB !== '1',

  // `next/image` requiere optimizar en runtime con un Node server. Bajo `export`
  // no hay server, así que desactivamos la optimización (las imágenes se sirven
  // tal cual desde el bundle).
  images: { unoptimized: true },

  // Variable hardcodeada en el bundle estático. El agente Python corre en un
  // puerto efímero distinto cada arranque; el renderer prefiere
  // `window.satAgent.baseUrl` (inyectado por el preload de Electron) sobre
  // esta env var. Aquí queda como fallback para dev fuera de Electron.
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8787',
    // Versión visible en la UI (Ayuda, Ajustes → Acerca de). Se hornea en build
    // desde package.json — única fuente de verdad del renderer.
    NEXT_PUBLIC_APP_VERSION: packageJson.version,
    // Entorno de Vercel (production | preview) para separar los reportes de
    // Sentry de las previews en la versión web. Vacío fuera de Vercel.
    NEXT_PUBLIC_VERCEL_ENV: process.env.VERCEL_ENV || '',
  },
};

export default nextConfig;
