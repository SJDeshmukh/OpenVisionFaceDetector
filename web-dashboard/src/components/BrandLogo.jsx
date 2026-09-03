const BrandLogo = ({ className = 'h-9 w-9', alt = 'TapInX' }) => (
  <img src="/tapinx-logo.svg" alt={alt} className={`shrink-0 object-contain ${className}`} />
);

export default BrandLogo;
