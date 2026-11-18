import { useEffect, useMemo, useRef, useState } from 'react';

const useReducedMotion = () => {
  const [reduced, setReduced] = useState(() => (
    typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  ));

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(media.matches);
    media.addEventListener?.('change', update);
    return () => media.removeEventListener?.('change', update);
  }, []);

  return reduced;
};

const CountUpNumber = ({ value, prefix = '', suffix = '', decimals = 0, duration = 900, className = '' }) => {
  const target = Number(value);
  const validNumber = Number.isFinite(target);
  const reducedMotion = useReducedMotion();
  const [displayValue, setDisplayValue] = useState(() => (reducedMotion && validNumber ? target : 0));
  const displayedRef = useRef(displayValue);

  const formatter = useMemo(() => new Intl.NumberFormat('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }), [decimals]);

  useEffect(() => {
    if (!validNumber) return undefined;
    if (reducedMotion) {
      displayedRef.current = target;
      setDisplayValue(target);
      return undefined;
    }

    const startValue = displayedRef.current;
    const difference = target - startValue;
    if (difference === 0) return undefined;

    let animationFrame;
    const startedAt = performance.now();
    const animate = (now) => {
      const progress = Math.min((now - startedAt) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const nextValue = startValue + (difference * eased);
      displayedRef.current = nextValue;
      setDisplayValue(nextValue);
      if (progress < 1) {
        animationFrame = window.requestAnimationFrame(animate);
      } else {
        displayedRef.current = target;
        setDisplayValue(target);
      }
    };

    animationFrame = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(animationFrame);
  }, [duration, reducedMotion, target, validNumber]);

  if (!validNumber) return <span className={className}>{value}</span>;

  const visibleValue = formatter.format(decimals > 0 ? displayValue : Math.round(displayValue));
  const finalValue = `${prefix}${formatter.format(target)}${suffix}`;
  return (
    <span className={`tabular-nums ${className}`} aria-label={finalValue}>
      <span aria-hidden="true">{prefix}{visibleValue}{suffix}</span>
    </span>
  );
};

export default CountUpNumber;
