const BrandLogo = ({ className = 'h-9 w-9', alt = 'TapInX', symbolOnly = false }) => (
  <img src={symbolOnly ? '/tapinx-symbol.svg' : '/tapinx-logo.svg'} alt={alt} className={`shrink-0 object-contain ${className}`} />
);

export default BrandLogo;
