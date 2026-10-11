import { Link, NavLink } from 'react-router-dom';
import './SiteNav.css';

/**
 * Keep DOM structure stable — GSAP pin + conditional React mounts crash the page.
 * Use `hidden` / `solid` classes only; do not unmount this header on scroll.
 */
export default function SiteNav({
  solid = false,
  showCta = true,
  hidden = false,
  hideLogo = false,
}) {
  const classes = [
    'site-nav',
    solid ? 'site-nav--solid' : '',
    hidden ? 'site-nav--hidden' : '',
    !showCta ? 'site-nav--no-cta' : '',
    hideLogo ? 'site-nav--no-logo' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <header className={classes} aria-hidden={hidden || undefined}>
      <div className="site-nav__logo-wrap">
        <Link to="/" className="site-nav__logo">
          unobio
        </Link>
      </div>
      <nav className="site-nav__links" aria-label="Primary">
        <a href="/#underwrite">Underwrite</a>
        <NavLink to="/request">Request</NavLink>
        <NavLink to="/report">Report</NavLink>
      </nav>
      <a href="/#underwrite" className="site-nav__cta">
        Underwrite →
      </a>
    </header>
  );
}
