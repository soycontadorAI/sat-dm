'use client';

import { formatDistanceToNow } from 'date-fns';
import { es } from 'date-fns/locale';

import { Icon } from '@/components/ui/icon';
import { cn } from '@/lib/utils';
import type { Anuncio, AnuncioCategoria } from '@/lib/anuncios';

const CATEGORIA_LABEL: Record<AnuncioCategoria, string> = {
  curso: 'Curso',
  taller: 'Taller',
  blog: 'Blog',
  oferta: 'Oferta',
  producto: 'Producto',
  aviso: 'Aviso',
};

interface Props {
  anuncio: Anuncio;
  read: boolean;
  onRead: () => void;
}

export function NotificationItem({ anuncio, read, onRead }: Props) {
  const fecha = formatFecha(anuncio.publishedAt);

  const inner = (
    <div className="flex items-start gap-2 px-3 py-3">
      <span
        className={cn(
          'mt-1.5 size-2 shrink-0 rounded-full',
          read ? 'bg-transparent' : 'bg-primary',
        )}
        aria-hidden
      />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-[11px] font-medium text-muted-foreground">
            {CATEGORIA_LABEL[anuncio.category]}
          </span>
          <span className="shrink-0 text-[10px] text-muted-foreground">{fecha}</span>
        </div>
        <h4 className={cn('text-sm leading-snug', !read && 'font-semibold')}>
          {anuncio.title}
        </h4>
        <p className="line-clamp-3 text-xs leading-relaxed text-muted-foreground">
          {anuncio.body}
        </p>
        {anuncio.link && (
          <span className="inline-flex items-center gap-1 text-xs text-primary">
            Ver más
            <Icon icon="ph:arrow-up-right-light" className="size-3" />
          </span>
        )}
      </div>
    </div>
  );

  if (anuncio.link) {
    return (
      <li>
        <a
          href={anuncio.link}
          target="_blank"
          rel="noopener noreferrer"
          onClick={onRead}
          className="block transition-colors hover:bg-secondary/50"
        >
          {inner}
        </a>
      </li>
    );
  }

  return (
    <li>
      <button
        type="button"
        onClick={onRead}
        className="block w-full text-left transition-colors hover:bg-secondary/50"
      >
        {inner}
      </button>
    </li>
  );
}

function formatFecha(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '';
  return formatDistanceToNow(new Date(t), { addSuffix: true, locale: es });
}
