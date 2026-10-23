// ---------------------------------------------------------------------------
// Feature flags de la app. Un solo punto para prender/apagar features en
// preparación sin borrar su código.
// ---------------------------------------------------------------------------

/**
 * Renovación de e.firma en línea (generar el .ren, bajar el respaldo de la
 * llave nueva, enviar, reanudar un envío fallido y descargar el certificado
 * pendiente). Con `false` la UI muestra el botón como «Disponible próximamente».
 *
 * Encendida en octubre de 2026. Estuvo apagada desde julio por miedo a que la
 * ejecución empacada en Windows (antivirus) cortara el trámite; el envío corre
 * dentro del agente con el mismo Chromium que la Constancia y la 32-D, y lo
 * que no se puede perder (la .key nueva) se persiste y se respalda antes de
 * enviar.
 *
 * Anotado `: boolean` a propósito: sin la anotación TS lo estrecharía al tipo
 * literal `false` y trataría las ramas habilitadas como código muerto — con
 * `boolean` sigue siendo un flag real que se puede cambiar a `true` sin tocar
 * nada más.
 */
export const RENOVACION_EFIRMA_HABILITADA: boolean = true;

/**
 * Planes v3 (F1 de docs/operacion/plan-app-v3.md en todoconta-apps): los tres
 * planes con selector anual o mensual en /suscripcion, el contador "8 de 10
 * empresas", los candados de MCP, API y Abacus según `license.capacidades` y el
 * tope de empresas. APAGADO: con `false` la app se ve igual que hoy aunque la
 * licencia ya traiga los campos nuevos (F0). El Día C se encienden solos con
 * `license.planes_v3_activo` (ver `usePlanesV3()`); este flag solo sirve para
 * verlos antes de tiempo en desarrollo.
 */
export const PLANES_V3: boolean = false;

/**
 * Navegación por espacios + ⌘K con órdenes (F3,
 * todoconta-apps/docs/producto/navegacion-espacios.md).
 *
 * Interruptor de disponibilidad (kill switch): con `true` la navegación nueva
 * se puede encender por instalación (`?labs=espacios` o Ajustes > Apariencia >
 * Navegación) y entra por default según `NAV_ESPACIOS_DEFAULT_DESDE`. Con
 * `false` todos ven la clásica, sin excepción (ni labs). Quien no la encienda
 * ve el menú plano de siempre. La regla completa vive en
 * `lib/navegacion-modo.ts` (`resolverModoNavegacion`).
 */
export const NAV_ESPACIOS: boolean = true;

/**
 * Desde este momento (lunes 2 de noviembre de 2026, 00:00 en la Ciudad de
 * México) las cuentas en prueba y las nuevas abren con la navegación por
 * espacios, salvo que la instalación haya elegido otra cosa. Las cuentas que ya
 * pagan siguen con la clásica y la pueden encender en Ajustes. Es una constante
 * de build: escritorio y web salen con la misma versión, así que el cambio cae
 * igual en los dos sin desplegar nada ese día (basta con que el release que la
 * trae salga antes).
 */
export const NAV_ESPACIOS_DEFAULT_DESDE: string = '2026-11-02T00:00:00-06:00';

/**
 * Fase 2 del despliegue (navegacion-espacios.md, 8.3): espacios por default
 * para TODOS. Mientras sea `false`, solo las cuentas en prueba y nuevas la
 * reciben por default (desde la fecha de arriba).
 */
export const NAV_ESPACIOS_PARA_TODOS: boolean = false;
