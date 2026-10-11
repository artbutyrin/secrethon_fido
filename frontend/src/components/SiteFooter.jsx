import { Link } from 'react-router-dom';
import './SiteFooter.css';

export default function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="site-footer__grid">
        <div>
          <p className="eyebrow">Unobio Bioplatform · Est 2024</p>
          <p className="site-footer__brand">unobio</p>
          <p className="site-footer__tag">
            AI-native investment underwriting for biotech assets.
          </p>
        </div>
        <div>
          <p className="eyebrow">Company</p>
          <ul>
            <li>
              <a href="/#approach">Approach</a>
            </li>
            <li>
              <Link to="/request">Request underwriting</Link>
            </li>
          </ul>
        </div>
        <div>
          <p className="eyebrow">Contact</p>
          <ul>
            <li>Cambridge, MA</li>
            <li>
              <a href="mailto:hello@unobio.com">hello@unobio.com</a>
            </li>
          </ul>
        </div>
      </div>
      <div className="site-footer__bar">
        <span>© {new Date().getFullYear()} Unobio</span>
        <span>Moving Beyond the Molecule</span>
      </div>
    </footer>
  );
}
