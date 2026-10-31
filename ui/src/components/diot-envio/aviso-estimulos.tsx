import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { URL_PORTAL_DIOT } from '@/lib/diot-envio';

/**
 * Límite del envío de la DIOT: TodoConta contesta "No" a "¿Aplicaste estímulos
 * fiscales?" y todavía no sabe capturarlos. Es de las pocas cosas que, si se
 * pasan por alto, dejan una declaración presentada MAL y sin reversa, así que va
 * en rojo, arriba y en todos los pasos (no se puede cerrar).
 *
 * Es el `Alert` destructivo de siempre con el fondo `destructive-bg` y un borde
 * más marcado: el mismo patrón, a todo color.
 */
export function AvisoEstimulos() {
  return (
    <Alert
      variant="destructive"
      role="alert"
      className="border-2 border-destructive/60 bg-destructive-bg px-5 py-4"
    >
      <Icon icon="ph:warning-light" className="size-5" />
      <AlertTitle className="text-base font-extrabold tracking-tight">
        Estímulos fiscales: TodoConta todavía no los cubre
      </AlertTitle>
      <AlertDescription className="space-y-3 text-destructive">
        <p className="leading-relaxed">
          Este envío contesta <strong>"No"</strong> a la pregunta{' '}
          <strong>"¿Aplicaste estímulos fiscales?"</strong> del portal del SAT. Si en este
          periodo aplicaste alguno, <strong>no uses este envío</strong>: presenta la DIOT
          manualmente en el portal, indicando ahí los estímulos. Una declaración presentada
          sin ellos no se deshace.
        </p>
        <Button variant="outline" size="sm" asChild className="border-destructive/50 bg-card text-destructive hover:bg-card">
          <a href={URL_PORTAL_DIOT} target="_blank" rel="noreferrer">
            <Icon icon="ph:arrow-square-out-light" className="size-4" />
            Abrir el portal de la DIOT del SAT
          </a>
        </Button>
      </AlertDescription>
    </Alert>
  );
}
