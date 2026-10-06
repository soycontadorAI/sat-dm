'use client';

import { useEffect, useState } from 'react';

import { cn } from '@/lib/utils';
import { atajosDe, esMac, formatearAtajo } from '@/lib/atajos';
import { useNavegacion } from '@/providers/navegacion-provider';
import { PageHeading } from '@/components/layout/page-heading';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Icon } from '@/components/ui/icon';

// ---------------------------------------------------------------------------
// Contenido estático de las preguntas frecuentes (copy sin tecnicismos).
// ---------------------------------------------------------------------------

interface FaqItem {
  q: string;
  a: string;
}

interface FaqGroup {
  grupo: string;
  icon: string;
  items: FaqItem[];
}

const FAQ_GROUPS: FaqGroup[] = [
  {
    grupo: 'Primeros pasos',
    icon: 'ph:squares-four-light',
    items: [
      {
        q: '¿Cómo agrego una empresa?',
        a: 'Ve a Empresas y toca "Agregar empresa". Solo necesitas el RFC y un acceso: tu e.firma (con su contraseña) o tu Contraseña del SAT (antes CIEC). Puedes registrar todas las empresas que manejes y cambiar entre ellas desde la parte superior del menú.',
      },
      {
        q: '¿Necesito e.firma o me basta con la Contraseña del SAT?',
        a: 'Las dos sirven. Con e.firma puedes hacer descargas masivas sin límite diario. Con la Contraseña del SAT puedes hacer descargas rápidas del portal, ideales para pocas facturas. Si tienes ambas, TodoConta elige la mejor opción para cada descarga.',
      },
    ],
  },
  {
    grupo: 'Descargas',
    icon: 'ph:download-simple-light',
    items: [
      {
        q: '¿Cómo descargo mis CFDIs?',
        a: 'Entra a Descargar CFDIs, elige el periodo y si quieres las emitidas, las recibidas o ambas, y toca "Solicitar descarga". Cuando estén listas las verás en el Historial y en Comprobantes.',
      },
      {
        q: '¿Cuál es la diferencia entre descarga masiva y descarga rápida?',
        a: 'La descarga masiva usa el Web Service del SAT con tu e.firma: no tiene límite diario y normalmente queda lista en un par de horas, aunque en días de mucha demanda el SAT puede tardar más. La descarga rápida trae las facturas directo del portal al momento, aunque está limitada al máximo de descargas que el portal permite (500 XML por día).',
      },
      {
        q: '¿Por qué a veces una descarga tarda más?',
        a: 'En la descarga masiva, el SAT recibe tu solicitud y la procesa cuando tiene los archivos listos. No depende de TodoConta. Te avisamos en cuanto estén disponibles para descargar.',
      },
    ],
  },
  {
    grupo: 'e.firma y seguridad',
    icon: 'ph:shield-check-light',
    items: [
      {
        q: 'Mi e.firma está por vencer, ¿qué hago?',
        a: 'Necesitas renovarla ante el SAT (en línea si aún está vigente, o presencialmente si ya venció). Cuando tengas los archivos nuevos, actualízalos en Empresas. Te avisamos cuando a tu e.firma le queden 30 días o menos.',
      },
      {
        q: '¿Es seguro guardar mi e.firma y mi Contraseña del SAT?',
        a: 'Sí. Se guardan protegidas y solo en este equipo; nunca se muestran a la vista ni se envían a internet. Solo se usan en el momento de conectarte con el SAT.',
      },
      {
        q: '¿Dónde se guardan mis facturas?',
        a: 'En la carpeta de descargas que elijas, ordenadas en subcarpetas por tipo y por RFC. Puedes cambiar la carpeta cuando quieras desde Ajustes.',
      },
    ],
  },
];

const GUIAS = [
  { icon: 'ph:book-open-light', titulo: 'Guía de primeros pasos', url: 'https://todoconta.com/desktop' },
  { icon: 'ph:play-light', titulo: 'Video: tu primera descarga', url: 'https://todoconta.com/desktop' },
  { icon: 'ph:files-light', titulo: 'Cómo exportar a Excel', url: 'https://todoconta.com/desktop' },
] as const;

// ---------------------------------------------------------------------------
// Pantalla
// ---------------------------------------------------------------------------

function ContactRow({ icon, label, value }: { icon: string; label: string; value: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="flex size-8.5 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
        <Icon icon={icon} className="size-4" />
      </span>
      <div className="min-w-0">
        <div className="text-[11.5px] font-medium text-muted-foreground">{label}</div>
        <div className="truncate text-[13.5px] font-semibold text-foreground">{value}</div>
      </div>
    </div>
  );
}

export default function AyudaPage() {
  const [query, setQuery] = useState('');
  const [abierta, setAbierta] = useState<string | null>('Primeros pasos-0');
  // Símbolo de los atajos (⌘ vs Ctrl); post-mount para no romper hidratación.
  const [mac, setMac] = useState(false);

  useEffect(() => {
    setMac(esMac());
  }, []);

  // La tarjeta de atajos sigue a la navegación de esta instalación (clásica o
  // espacios): se regenera sola desde lib/atajos.ts.
  const { modo } = useNavegacion();
  const atajos = atajosDe(modo);
  const gruposAtajos = [...new Set(atajos.map((a) => a.grupo))];

  const q = query.trim().toLowerCase();
  const grupos = FAQ_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter(
      (it) => !q || it.q.toLowerCase().includes(q) || it.a.toLowerCase().includes(q),
    ),
  })).filter((g) => g.items.length > 0);

  const version = process.env.NEXT_PUBLIC_APP_VERSION;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeading
        title="Ayuda"
        description="Encuentra respuestas rápidas o escríbenos si necesitas una mano."
      />

      {/* Buscador */}
      <div className="flex items-center gap-3 rounded-xl border border-input bg-card px-4 py-3 shadow-xs">
        <Icon icon="ph:magnifying-glass-light" className="size-4.5 shrink-0 text-muted-foreground" />
        <input
          className="flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
          placeholder="Busca una pregunta…  p. ej. descargar, e.firma, Contraseña"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {query && (
          <Button variant="ghost" size="sm" onClick={() => setQuery('')}>
            Limpiar
          </Button>
        )}
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[1.55fr_1fr]">
        {/* FAQ */}
        <div className="space-y-5">
          {grupos.length === 0 && (
            <Card>
              <CardContent className="py-8 text-center text-muted-foreground">
                <div className="mb-1 font-semibold text-foreground">
                  Sin resultados para "{query}"
                </div>
                <div className="text-sm">
                  Prueba con otra palabra o escríbenos directamente.
                </div>
              </CardContent>
            </Card>
          )}
          {grupos.map((g) => (
            <div key={g.grupo}>
              <div className="mb-2.5 ml-0.5 flex items-center gap-2 text-xs font-bold uppercase tracking-wide text-muted-foreground">
                <Icon icon={g.icon} className="size-3.75" />
                {g.grupo}
              </div>
              <Card className="overflow-hidden py-0">
                {g.items.map((it, i) => {
                  const id = `${g.grupo}-${i}`;
                  const isOpen = abierta === id;
                  return (
                    <div
                      key={id}
                      className={cn(i > 0 && 'border-t border-border')}
                    >
                      <button
                        className={cn(
                          'flex w-full items-center justify-between gap-3.5 px-4.5 py-3.75 text-left text-sm font-semibold transition-colors hover:bg-secondary',
                          isOpen ? 'text-primary' : 'text-foreground',
                        )}
                        onClick={() => setAbierta(isOpen ? null : id)}
                        aria-expanded={isOpen}
                      >
                        <span>{it.q}</span>
                        <Icon
                          icon="ph:caret-down-light"
                          className={cn(
                            'size-4 shrink-0 text-muted-foreground transition-transform',
                            isOpen && 'rotate-180',
                          )}
                        />
                      </button>
                      {isOpen && (
                        <div className="max-w-prose px-4.5 pb-4 text-[13.5px] leading-relaxed text-muted-foreground">
                          {it.a}
                        </div>
                      )}
                    </div>
                  );
                })}
              </Card>
            </div>
          ))}
        </div>

        {/* Contacto + guías + versión */}
        <div className="space-y-4">
          <Card>
            <CardContent className="space-y-4">
              <div>
                <div className="text-[15px] font-bold">
                  ¿No encontraste lo que buscabas?
                </div>
                <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">
                  Escríbenos y te ayudamos. Solemos responder el mismo día hábil.
                </p>
              </div>
              <div className="space-y-2.5">
                <ContactRow icon="ph:envelope-simple-light" label="Correo" value="soporte@todoconta.com" />
                <ContactRow icon="ph:chat-circle-light" label="WhatsApp" value="+52 55 1234 5678" />
                <ContactRow icon="ph:clock-light" label="Horario" value="Lun a Vie, 9–18 h" />
              </div>
              <Button className="w-full" asChild>
                <a href="mailto:soporte@todoconta.com">
                  <Icon icon="ph:chat-circle-light" className="size-4" />
                  Escríbenos
                </a>
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardContent>
              <div className="mb-2.5 text-[15px] font-bold">Guías y tutoriales</div>
              <div className="-mx-2 flex flex-col">
                {GUIAS.map((guia) => (
                  <a
                    key={guia.titulo}
                    href={guia.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="group flex items-center gap-3 rounded-lg px-2 py-2.5 text-[13.5px] font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                  >
                    <Icon icon={guia.icon} className="size-4 shrink-0" />
                    <span className="flex-1">{guia.titulo}</span>
                    <Icon
                      icon="ph:arrow-right-light"
                      className="size-3.75 shrink-0 text-muted-foreground/60 group-hover:text-primary"
                    />
                  </a>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent>
              <div className="mb-2.5 flex items-center gap-2 text-[15px] font-bold">
                <Icon icon="ph:keyboard-light" className="size-4.5 text-muted-foreground" />
                Atajos de teclado
              </div>
              <div className="space-y-3">
                {gruposAtajos.map((grupo) => (
                  <div key={grupo}>
                    <div className="mb-1.5 text-xs font-semibold text-ghost">{grupo}</div>
                    <div className="flex flex-col gap-1.5">
                      {atajos.filter((a) => a.grupo === grupo).map((a) => (
                        <div
                          key={a.id}
                          className="flex items-center justify-between gap-3 text-[13.5px]"
                        >
                          <span className="text-muted-foreground">{a.descripcion}</span>
                          <kbd className="shrink-0 rounded border bg-muted px-1.5 py-px font-sans text-[10.5px] text-muted-foreground">
                            {formatearAtajo(a, mac)}
                          </kbd>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <div className="flex items-center gap-2.5 px-1 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1 rounded-full bg-success/10 px-2 py-0.5 font-semibold text-success">
              <Icon icon="ph:check-circle-light" className="size-3" />
              Estás al día
            </span>
            <span>TodoConta Desktop{version ? ` · versión ${version}` : ''}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
