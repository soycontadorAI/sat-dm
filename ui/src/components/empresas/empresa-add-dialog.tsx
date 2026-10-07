'use client';

import { useRef, useState } from 'react';

import { cn } from '@/lib/utils';
import { Icon } from '@/components/ui/icon';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { mensajeDeError } from '@/lib/errores';
import { topeEmpresasDeError, type TopeEmpresas } from '@/lib/api-client';

interface EmpresaAddDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  addFiel: (cer: File, key: File, password: string) => Promise<void>;
  addCiec: (rfc: string, ciec: string) => Promise<void>;
  /**
   * El agente respondió 402: el plan no tiene lugar para otra empresa. Si se
   * pasa, el modal se cierra y el padre muestra el diálogo del tope (Archivar /
   * Cambiar de plan); si no, el mensaje sale como cualquier error.
   */
  onTope?: (tope: TopeEmpresas) => void;
}

/**
 * Modal de alta de empresa, simplificado: solo el acceso (e.firma o CIEC), sin
 * pedir el nombre — se completa solo (razón social del certificado o RFC) en
 * cuanto conectamos con el SAT.
 */
export function EmpresaAddDialog({
  open,
  onOpenChange,
  addFiel,
  addCiec,
  onTope,
}: EmpresaAddDialogProps) {
  // e.firma
  const [cer, setCer] = useState<File | null>(null);
  const [key, setKey] = useState<File | null>(null);
  const [password, setPassword] = useState('');
  // CIEC
  const [rfc, setRfc] = useState('');
  const [ciec, setCiec] = useState('');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setCer(null);
    setKey(null);
    setPassword('');
    setRfc('');
    setCiec('');
    setError(null);
  }

  function handleOpenChange(next: boolean) {
    if (!next) reset();
    onOpenChange(next);
  }

  async function run(fn: () => Promise<void>) {
    setLoading(true);
    setError(null);
    try {
      await fn();
      handleOpenChange(false);
    } catch (err) {
      const tope = topeEmpresasDeError(err);
      if (tope && onTope) {
        handleOpenChange(false);
        onTope(tope);
        return;
      }
      setError(mensajeDeError(err));
    } finally {
      setLoading(false);
    }
  }

  const fielOk = !!cer && !!key && password.length > 0;
  const ciecOk = rfc.trim().length >= 12 && ciec.length > 0;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Agregar empresa</DialogTitle>
          <DialogDescription>
            Tus accesos se guardan protegidos y solo en este equipo. Tu e.firma
            nunca sale de tu computadora.
          </DialogDescription>
        </DialogHeader>

        {/* min-w-0: el DialogContent es un grid y este Tabs es su grid item;
            sin esto el item no encoge bajo su min-content y un nombre de archivo
            largo en el FileField rompe el ancho del modal (el truncate no aplica). */}
        <Tabs defaultValue="fiel" className="min-w-0">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="fiel">
              <Icon icon="ph:shield-check-light" className="size-4" /> e.firma
            </TabsTrigger>
            <TabsTrigger value="ciec">
              <Icon icon="ph:key-light" className="size-4" /> Contraseña
            </TabsTrigger>
          </TabsList>

          {/* e.firma */}
          <TabsContent value="fiel" className="mt-4">
            <form
              className="space-y-3.5"
              onSubmit={(e) => {
                e.preventDefault();
                if (fielOk) run(() => addFiel(cer!, key!, password));
              }}
            >
              <FileField
                label="Certificado (.cer)"
                accept=".cer"
                file={cer}
                onPick={setCer}
              />
              <FileField
                label="Llave privada (.key)"
                accept=".key"
                file={key}
                onPick={setKey}
              />
              <Field label="Contraseña de la clave privada" htmlFor="fiel-pass"
                     hint={<RespaldoFielTooltip />}>
                <Input id="fiel-pass" type="password" value={password}
                       placeholder="••••••••"
                       onChange={(e) => setPassword(e.target.value)} />
              </Field>
              <HintNombre />
              <Button type="submit" className="w-full" disabled={!fielOk || loading}>
                {loading ? <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" /> : <Icon icon="ph:shield-check-light" className="size-4" />}
                Registrar con e.firma
              </Button>
            </form>
          </TabsContent>

          {/* CIEC */}
          <TabsContent value="ciec" className="mt-4">
            <form
              className="space-y-3.5"
              onSubmit={(e) => {
                e.preventDefault();
                if (ciecOk) run(() => addCiec(rfc.trim().toUpperCase(), ciec));
              }}
            >
              <Field label="RFC" htmlFor="ciec-rfc">
                <Input id="ciec-rfc" value={rfc} placeholder="XAXX010101000"
                       className="font-mono uppercase"
                       onChange={(e) => setRfc(e.target.value)} />
              </Field>
              <Field label="Contraseña del SAT (antes CIEC)" htmlFor="ciec-pass">
                <Input id="ciec-pass" type="password" value={ciec}
                       placeholder="••••••••"
                       onChange={(e) => setCiec(e.target.value)} />
              </Field>
              <HintNombre />
              <Button type="submit" className="w-full" disabled={!ciecOk || loading}>
                {loading ? <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" /> : <Icon icon="ph:key-light" className="size-4" />}
                Registrar con Contraseña
              </Button>
            </form>
          </TabsContent>
        </Tabs>

        {error && (
          <Alert variant="destructive">
            <AlertTitle>No se pudo registrar</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
      </DialogContent>
    </Dialog>
  );
}

function HintNombre() {
  return (
    <div className="flex items-start gap-2 rounded-lg bg-accent px-3 py-2.5 text-xs leading-relaxed text-accent-foreground">
      <Icon icon="ph:info-light" className="mt-px size-3.75 shrink-0" />
      El nombre de la empresa se completa en cuanto conectamos con el SAT.
    </div>
  );
}

/**
 * Tooltip de privacidad/respaldo de la e.firma: un icono (?) junto al campo de
 * contraseña que, al pasar el cursor (o al enfocar con teclado), explica que la
 * copia .cer/.key se respalda en la carpeta de descargas y que la contraseña nunca
 * se escribe en texto plano. Va como tooltip para no gastar espacio en el modal.
 */
function RespaldoFielTooltip() {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label="Qué pasa con mi e.firma y mi contraseña"
          tabIndex={0}
          className="inline-flex size-4 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
        >
          <Icon icon="ph:question-light" className="size-3.75" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="top" align="start" className="w-72 rounded-xl p-3.5 text-left leading-relaxed">
        Tu e.firma se queda en tu equipo; nunca la subimos a ningún servidor.
        Guardamos una copia de respaldo de tu .cer/.key en tu carpeta de descargas.{' '}
        <strong className="font-semibold">Tu contraseña no se guarda en texto plano</strong>{' '}
        Resguárdala: no podemos recuperarla.
      </TooltipContent>
    </Tooltip>
  );
}

function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5">
        <Label htmlFor={htmlFor}>{label}</Label>
        {hint}
      </div>
      {children}
    </div>
  );
}

/** Selector de archivo estilo prototipo: pill "Seleccionar" + nombre + check. */
function FileField({
  label,
  accept,
  file,
  onPick,
}: {
  label: string;
  accept: string;
  file: File | null;
  onPick: (f: File | null) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <button
        type="button"
        onClick={() => ref.current?.click()}
        className={cn(
          'flex w-full items-center gap-2.5 rounded-lg border bg-card p-1.5 pl-2 text-left transition-colors',
          file ? 'border-success' : 'border-input hover:border-primary',
        )}
      >
        <span className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-secondary px-2.5 py-1.5 text-xs font-semibold text-secondary-foreground">
          <Icon icon="ph:upload-light" className="size-3.5" />
          Seleccionar
        </span>
        <span
          className={cn(
            'min-w-0 flex-1 truncate text-xs',
            file ? 'font-medium text-foreground' : 'text-muted-foreground',
          )}
        >
          {file ? file.name : 'Ningún archivo seleccionado'}
        </span>
        {file && (
          <Icon
            icon="ph:check-circle-light"
            className="mr-1 size-4 shrink-0 text-success"
          />
        )}
        <input
          ref={ref}
          type="file"
          accept={accept}
          className="hidden"
          onChange={(e) => onPick(e.target.files?.[0] ?? null)}
        />
      </button>
    </div>
  );
}
