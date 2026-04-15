type SkeletonProps = {
  className?: string;
  'aria-label'?: string;
};

/**
 * Minimal pulse block. Compose by passing width/height/rounded classes.
 * Uses a gradient + `animate-shimmer` so a light band sweeps across.
 */
export function Skeleton({ className = '', ...rest }: SkeletonProps) {
  return (
    <div
      aria-hidden={!rest['aria-label']}
      role={rest['aria-label'] ? 'status' : undefined}
      className={`relative overflow-hidden rounded-md bg-slate-100 ${className}`}
      {...rest}
    >
      <div className="absolute inset-0 animate-shimmer bg-[linear-gradient(90deg,transparent,rgba(255,255,255,0.65),transparent)] bg-[length:200%_100%]" />
    </div>
  );
}

export function SkeletonText({
  lines = 1,
  className = ''
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={`space-y-2 ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={`h-3 ${i === lines - 1 && lines > 1 ? 'w-2/3' : 'w-full'}`}
        />
      ))}
    </div>
  );
}
